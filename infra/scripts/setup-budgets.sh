#!/usr/bin/env bash
# Archimedes — AWS spend guardrails (Setup Guide Part 1, Step 5).
#
# Two brakes, neither perfect, together they protect from a runaway bill:
#   1. AWS Budgets   -> email alerts at 50/80/100% + a low tripwire budget.
#   2. Budget Action -> at ~90% auto-attaches a deny-Bedrock IAM policy (the auto-brake).
#   3. Cost Anomaly Detection -> ML early-warning on unusual spend.
#   4. Cost-allocation tag activation -> per-component breakdown in Cost Explorer.
# (Pair this with the app-level daily token cap in code — that is brake #0.)
#
# AWS has NO native hard "stop at $X": budgets alert, actions detach permissions,
# nothing guarantees zero further spend. That is why we layer brakes.
#
# DRY-RUN BY DEFAULT. Nothing is created unless you pass --apply.
#
#   ./setup-budgets.sh                              # print the plan, change nothing
#   ./setup-budgets.sh --apply                      # budgets + alerts + anomaly detection (safe, pre-stack)
#   ./setup-budgets.sh --apply --with-deny-action   # ALSO wire the Bedrock-deny budget action
#                                                   #   (run only AFTER `terraform apply` created the app role)
#
# Requires: AWS_PROFILE exported (e.g. ArchimedesDanAdmin), aws CLI v2, jq.
# Run via the pinned env: AWS_PROFILE=ArchimedesDanAdmin conda run -n archimedes ./setup-budgets.sh ...
set -euo pipefail

# ─── Config (edit these) ─────────────────────────────────────────────────────
ACCOUNT_ID="${ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)}"  # auto-detect from active profile; override via env
REGION="${AWS_REGION:-us-east-1}"
ALERT_EMAIL="${ALERT_EMAIL:?set ALERT_EMAIL env, e.g. export ALERT_EMAIL=ops@brownehq.com (kept out of the repo so the root alias is never committed)}"  # budget + anomaly alerts
MONTHLY_LIMIT="200"                         # USD/month target
TRIPWIRE_LIMIT="25"                         # USD/month early smoke alarm
ANOMALY_IMPACT_USD="10"                     # alert when a single anomaly's impact >= this
TAG_KEY="project"                           # cost-allocation tag to activate (value: archimedes)
# Used only with --with-deny-action. Set to the IAM ROLE NAME your backend uses to
# call Bedrock (see `terraform output` / infra IAM). The deny policy is attached to it at ~90%.
DENY_TARGET_ROLE="archimedes-ec2-role"
MAIN_BUDGET="archimedes-monthly-${MONTHLY_LIMIT}"
TRIPWIRE_BUDGET="archimedes-tripwire-${TRIPWIRE_LIMIT}"
DENY_POLICY="archimedes-bedrock-deny"
BUDGETS_ROLE="archimedes-budgets-action-role"
# ─────────────────────────────────────────────────────────────────────────────

APPLY=false; WITH_DENY=false
for a in "$@"; do case "$a" in
  --apply) APPLY=true;;
  --with-deny-action) WITH_DENY=true;;
  -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
  *) echo "unknown arg: $a" >&2; exit 2;;
esac; done

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
do_() { printf '  + %s\n' "$*"; if $APPLY; then eval "$*"; fi; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

$APPLY && echo ">>> APPLY MODE — resources WILL be created in account ${ACCOUNT_ID}" \
        || echo ">>> DRY RUN — nothing will be created. Re-run with --apply to execute."

# ─── 1. Main $MONTHLY_LIMIT/mo budget with 50/80/100% alerts ──────────────────
say "Budget: ${MAIN_BUDGET} (\$${MONTHLY_LIMIT}/mo, alerts 50/80/100% + forecast)"
cat > "$TMP/budget-main.json" <<JSON
{ "BudgetName": "${MAIN_BUDGET}",
  "BudgetLimit": { "Amount": "${MONTHLY_LIMIT}", "Unit": "USD" },
  "TimeUnit": "MONTHLY", "BudgetType": "COST" }
JSON
cat > "$TMP/notes-main.json" <<JSON
[ {"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":50,"ThresholdType":"PERCENTAGE"},
   "Subscribers":[{"SubscriptionType":"EMAIL","Address":"${ALERT_EMAIL}"}]},
  {"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"},
   "Subscribers":[{"SubscriptionType":"EMAIL","Address":"${ALERT_EMAIL}"}]},
  {"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"},
   "Subscribers":[{"SubscriptionType":"EMAIL","Address":"${ALERT_EMAIL}"}]},
  {"Notification":{"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"},
   "Subscribers":[{"SubscriptionType":"EMAIL","Address":"${ALERT_EMAIL}"}]} ]
JSON
if aws budgets describe-budget --account-id "$ACCOUNT_ID" --budget-name "$MAIN_BUDGET" >/dev/null 2>&1; then
  echo "  (exists — skipping create)"
else
  do_ "aws budgets create-budget --account-id $ACCOUNT_ID --budget file://$TMP/budget-main.json --notifications-with-subscribers file://$TMP/notes-main.json"
fi

# ─── 2. Low tripwire budget (early smoke alarm) ───────────────────────────────
say "Budget: ${TRIPWIRE_BUDGET} (\$${TRIPWIRE_LIMIT}/mo tripwire, alert at 100%)"
cat > "$TMP/budget-trip.json" <<JSON
{ "BudgetName": "${TRIPWIRE_BUDGET}",
  "BudgetLimit": { "Amount": "${TRIPWIRE_LIMIT}", "Unit": "USD" },
  "TimeUnit": "MONTHLY", "BudgetType": "COST" }
JSON
cat > "$TMP/notes-trip.json" <<JSON
[ {"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"},
   "Subscribers":[{"SubscriptionType":"EMAIL","Address":"${ALERT_EMAIL}"}]} ]
JSON
if aws budgets describe-budget --account-id "$ACCOUNT_ID" --budget-name "$TRIPWIRE_BUDGET" >/dev/null 2>&1; then
  echo "  (exists — skipping create)"
else
  do_ "aws budgets create-budget --account-id $ACCOUNT_ID --budget file://$TMP/budget-trip.json --notifications-with-subscribers file://$TMP/notes-trip.json"
fi

# ─── 3. Cost Anomaly Detection (ML early warning) ─────────────────────────────
say "Cost Anomaly Detection (per-service monitor + email subscription)"
MON_ARN="$(aws ce get-anomaly-monitors --query "AnomalyMonitors[?MonitorName=='archimedes-monitor'].MonitorArn | [0]" --output text 2>/dev/null || true)"
if [ -n "${MON_ARN:-}" ] && [ "$MON_ARN" != "None" ]; then
  echo "  monitor exists: $MON_ARN"
else
  echo "  + aws ce create-anomaly-monitor --anomaly-monitor '{MonitorName:archimedes-monitor,MonitorType:DIMENSIONAL,MonitorDimension:SERVICE}'"
  if $APPLY; then
    MON_ARN="$(aws ce create-anomaly-monitor --anomaly-monitor '{"MonitorName":"archimedes-monitor","MonitorType":"DIMENSIONAL","MonitorDimension":"SERVICE"}' --query MonitorArn --output text)"
    echo "  created: $MON_ARN"
  fi
fi
cat > "$TMP/anomaly-sub.json" <<JSON
{ "SubscriptionName":"archimedes-anomaly-alerts",
  "MonitorArnList":["${MON_ARN:-MONITOR_ARN_PENDING}"],
  "Subscribers":[{"Type":"EMAIL","Address":"${ALERT_EMAIL}"}],
  "Frequency":"DAILY",
  "ThresholdExpression":{"Dimensions":{"Key":"ANOMALY_TOTAL_IMPACT_ABSOLUTE","Values":["${ANOMALY_IMPACT_USD}"],"MatchOptions":["GREATER_THAN_OR_EQUAL"]}} }
JSON
do_ "aws ce create-anomaly-subscription --anomaly-subscription file://$TMP/anomaly-sub.json"

# ─── 4. Activate cost-allocation tag (needs a tagged resource to exist first) ─
say "Activate cost-allocation tag '${TAG_KEY}'  (re-run post-apply if it 404s)"
echo "  NOTE: a tag key only becomes activatable AFTER a resource carrying it exists."
echo "        Harmless to run now; if it errors, re-run after 'terraform apply'."
do_ "aws ce update-cost-allocation-tags-status --cost-allocation-tags-status '[{\"TagKey\":\"${TAG_KEY}\",\"Status\":\"Active\"}]' || echo '  (tag not seen yet — re-run post-apply)'"

# ─── 5. Budget Action: deny Bedrock at ~90% (POST-APPLY only) ─────────────────
if ! $WITH_DENY; then
  say "Budget Action (Bedrock deny) — SKIPPED"
  echo "  Re-run with --with-deny-action AFTER 'terraform apply' creates role '${DENY_TARGET_ROLE}'."
else
  say "Budget Action: attach '${DENY_POLICY}' to role '${DENY_TARGET_ROLE}' at 90%"
  # 5a. Deny policy — denies only Bedrock model invocation (NOT a deny-all; you keep admin).
  cat > "$TMP/deny.json" <<'JSON'
{ "Version":"2012-10-17",
  "Statement":[{"Sid":"DenyBedrockInvoke","Effect":"Deny",
    "Action":["bedrock:InvokeModel","bedrock:InvokeModelWithResponseStream","bedrock:Converse","bedrock:ConverseStream"],
    "Resource":"*"}] }
JSON
  DENY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${DENY_POLICY}"
  if aws iam get-policy --policy-arn "$DENY_ARN" >/dev/null 2>&1; then
    echo "  deny policy exists: $DENY_ARN"
  else
    do_ "aws iam create-policy --policy-name $DENY_POLICY --policy-document file://$TMP/deny.json"
  fi
  # 5b. Execution role Budgets assumes to (de)attach the deny policy on the target role.
  cat > "$TMP/trust.json" <<'JSON'
{ "Version":"2012-10-17",
  "Statement":[{"Effect":"Allow","Principal":{"Service":"budgets.amazonaws.com"},"Action":"sts:AssumeRole"}] }
JSON
  cat > "$TMP/exec-perms.json" <<JSON
{ "Version":"2012-10-17",
  "Statement":[{"Effect":"Allow","Action":["iam:AttachRolePolicy","iam:DetachRolePolicy","iam:ListAttachedRolePolicies","iam:GetRole"],
    "Resource":"arn:aws:iam::${ACCOUNT_ID}:role/${DENY_TARGET_ROLE}"}] }
JSON
  if aws iam get-role --role-name "$BUDGETS_ROLE" >/dev/null 2>&1; then
    echo "  budgets-action role exists: $BUDGETS_ROLE"
  else
    do_ "aws iam create-role --role-name $BUDGETS_ROLE --assume-role-policy-document file://$TMP/trust.json"
    do_ "aws iam put-role-policy --role-name $BUDGETS_ROLE --policy-name attach-bedrock-deny --policy-document file://$TMP/exec-perms.json"
  fi
  # 5c. The action: at 90% ACTUAL, attach the deny policy to the target role.
  cat > "$TMP/action-def.json" <<JSON
{ "IamActionDefinition": { "PolicyArn":"${DENY_ARN}", "Roles":["${DENY_TARGET_ROLE}"] } }
JSON
  do_ "aws budgets create-budget-action --account-id $ACCOUNT_ID --budget-name $MAIN_BUDGET \
      --notification-type ACTUAL --action-type APPLY_IAM_POLICY \
      --action-threshold ActionThresholdValue=90,ActionThresholdType=PERCENTAGE \
      --definition file://$TMP/action-def.json \
      --execution-role-arn arn:aws:iam::${ACCOUNT_ID}:role/${BUDGETS_ROLE} \
      --approval-model AUTOMATIC \
      --subscribers SubscriptionType=EMAIL,Address=${ALERT_EMAIL}"
fi

say "Done."
$APPLY || echo "(dry run — re-run with --apply to create the above)"
