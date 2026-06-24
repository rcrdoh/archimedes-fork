# Bedrock Model Cost Comparison — us-east-1, on-demand

**Generated:** 2026-06-24 · account `037613907429` · via the AWS Price List API
(`pricing get-products --service-code AmazonBedrock`) + live `bedrock-runtime converse`
availability probes. Prices are **standard us-east-1 on-demand, USD per 1M tokens.**

## TL;DR

- The **cheapest competitive text models on Bedrock are all non-Anthropic**, and — unlike
  Anthropic models, which 404 until the one-time account **use-case form** is submitted —
  **they are invokable immediately** (confirmed by live probe under our role).
- So we can have a **real LLM live right now**, no waiting on the Anthropic form, by pointing
  the backend at one of these. Anthropic (Haiku 4.5 ≈ $1/$5, Sonnet/Opus pricier) stays the
  **premium / paid-tier** option once the form clears.
- For **multi-model support + a user-facing cost picker**, integrate via the **Bedrock
  Converse API** — one request/response shape across *all* providers. Our current
  `BedrockBackend` is Anthropic-SDK-specific; a Converse-based backend unlocks model-switching
  and the live $/1M surface in a single code path. (Roadmap T1.7-adjacent.)

## Recommended "works now" picks (no form, confirmed invokable)

| Model | modelId | Input $/1M | Output $/1M | Why |
|---|---|---:|---:|---|
| **Amazon Nova Micro** | `amazon.nova-micro-v1:0` | $0.035 | $0.140 | Cheapest; AWS-native; fast |
| **Z.AI GLM 4.7 Flash** | `zai.glm-4.7-flash` | $0.035 | $0.200 | Team has GLM experience |
| **Amazon Nova Lite** | `amazon.nova-lite-v1:0` | $0.060 | $0.240 | Step up from Micro |
| **Moonshot Kimi K2.5** | `moonshotai.kimi-k2.5` | $0.300 | $1.500 | StockBench top-tier reasoner |
| **DeepSeek v3.2** | `deepseek.v3.2` | $0.310 | $0.925 | Strong cheap reasoner |
| **Meta Llama 3.3 70B** | `us.meta.llama3-3-70b-instruct-v1:0` | $0.720 | $0.720 | Open-weight workhorse |

Also confirmed working now: Amazon Nova Pro, Llama 4 Scout, Mistral Small, Qwen3 32B.
OpenAI `gpt-oss-20b` responds but returns a reasoning-shaped payload (needs different parsing).

> **For comparison — our current default, Anthropic Haiku 4.5**, is ≈ **$1.00 in / $5.00 out**
> per 1M (from the agreement rate card; batch ≈ $0.50/$2.50). It's ~28× the input cost of Nova
> Micro — good as a premium tier, overkill as the free default.

## Full on-demand price table (74 text models, cheapest first)

Blended = input×0.75 + output×0.25 (a generation-skewed proxy). Sorted by blended.

| # | Provider | Model | Input $/1M | Output $/1M | Blended |
|---|----------|-------|-----------:|------------:|--------:|
| 1 | Mistral | Voxtral Mini 1.0 | $0.020 | $0.020 | $0.020 |
| 2 | Google | Gemma 3 4B | $0.020 | $0.040 | $0.025 |
| 3 | Google | google.gemma-4-e2b | $0.020 | $0.040 | $0.025 |
| 4 | OpenAI | GPT OSS Safeguard 20B | $0.030 | $0.100 | $0.048 |
| 5 | Mistral | Ministral 3B 3.0 | $0.050 | $0.050 | $0.050 |
| 6 | Nvidia | Nemotron Nano 3 30B | $0.030 | $0.120 | $0.053 |
| 7 | Nvidia | NVIDIA Nemotron Nano 2 | $0.030 | $0.120 | $0.053 |
| 8 | Amazon | Nova Micro | $0.035 | $0.140 | $0.061 |
| 9 | OpenAI | gpt-oss-20b | $0.035 | $0.150 | $0.064 |
| 10 | Mistral | Ministral 8B 3.0 | $0.070 | $0.070 | $0.070 |
| 11 | Mistral | Voxtral Small 1.0 | $0.050 | $0.150 | $0.075 |
| 12 | Google | Gemma 3 12B | $0.050 | $0.150 | $0.075 |
| 13 | Z.AI | GLM 4.7 Flash | $0.035 | $0.200 | $0.076 |
| 14 | Google | google.gemma-4-26b-a4b | $0.065 | $0.200 | $0.099 |
| 15 | Mistral | Ministral 14B 3.0 | $0.100 | $0.100 | $0.100 |
| 16 | Meta | Llama 3.2 1B | $0.100 | $0.100 | $0.100 |
| 17 | Google | google.gemma-4-31b | $0.070 | $0.200 | $0.102 |
| 18 | Amazon | Nova Lite | $0.060 | $0.240 | $0.105 |
| 19 | Amazon | Nova Sonic | $0.060 | $0.240 | $0.105 |
| 20 | OpenAI | GPT OSS Safeguard 120B | $0.070 | $0.300 | $0.128 |
| 21 | OpenAI | gpt-oss-120b | $0.075 | $0.300 | $0.131 |
| 22 | Qwen | Qwen3 Coder 30B A3B | $0.075 | $0.300 | $0.131 |
| 23 | Qwen | Qwen3 32B | $0.075 | $0.300 | $0.131 |
| 24 | Writer | Writer Palmyra Vision 7B | $0.075 | $0.300 | $0.131 |
| 25 | Nvidia | NVIDIA Nemotron 3 Super 120B A12B | $0.075 | $0.325 | $0.138 |
| 26 | Google | Gemma 3 27B | $0.120 | $0.190 | $0.138 |
| 27 | Meta | Llama 3.2 3B | $0.150 | $0.150 | $0.150 |
| 28 | Nvidia | NVIDIA Nemotron Nano 2 VL | $0.100 | $0.300 | $0.150 |
| 29 | Meta | Llama 3.2 11B | $0.160 | $0.160 | $0.160 |
| 30 | Mistral | Mistral 7B | $0.150 | $0.200 | $0.162 |
| 31 | Qwen | Qwen3 235B A22B 2507 | $0.110 | $0.440 | $0.193 |
| 32 | Qwen | Qwen3 Next 80B A3B | $0.070 | $0.600 | $0.202 |
| 33 | Meta | Llama 3.1 8B | $0.220 | $0.220 | $0.220 |
| 34 | Anthropic | Claude 3 Haiku | $0.250 | $1.250 | $0.250* |
| 35 | Minimax AI | Minimax M2.1 | $0.150 | $0.600 | $0.262 |
| 36 | Minimax AI | Minimax M2 | $0.150 | $0.600 | $0.262 |
| 37 | Minimax AI | MiniMax M2.5 | $0.150 | $0.600 | $0.262 |
| 38 | Meta | Llama 4 Scout 17B | $0.170 | $0.660 | $0.292 |
| 39 | Qwen | Qwen3 Coder Next | $0.250 | $0.600 | $0.338 |
| 40 | Mistral | Magistral Small 1.2 | $0.250 | $0.750 | $0.375 |
| 41 | Mistral | Mistral Large 3 | $0.250 | $0.750 | $0.375 |
| 42 | Meta | Llama 3 8B | $0.300 | $0.600 | $0.375 |
| 43 | Qwen | Qwen3 Coder 480B A35B | $0.225 | $0.900 | $0.394 |
| 44 | Mistral AI | Devstral | $0.200 | $1.000 | $0.400 |
| 45 | Meta | Llama 4 Maverick 17B | $0.240 | $0.970 | $0.423 |
| 46 | DeepSeek | DeepSeek V3.1 | $0.290 | $0.840 | $0.427 |
| 47 | DeepSeek | DeepSeek v3.2 | $0.310 | $0.925 | $0.464 |
| 48 | Amazon | Nova 2.0 Lite | $0.165 | $1.375 | $0.468 |
| 49 | Z.AI | GLM 4.7 | $0.300 | $1.100 | $0.500 |
| 50 | Amazon | Nova 2.0 Omni | $0.200 | $1.400 | $0.500 |
| 51 | Mistral | Mixtral 8x7B | $0.450 | $0.700 | $0.512 |
| 52 | Qwen | Qwen3 VL 235B A22B | $0.260 | $1.330 | $0.527 |
| 53 | Moonshot AI | Kimi K2 Thinking | $0.300 | $1.250 | $0.537 |
| 54 | Kimi AI | Kimi K2 Thinking | $0.300 | $1.250 | $0.537 |
| 55 | Moonshot AI | Kimi K2.5 | $0.300 | $1.500 | $0.600 |
| 56 | Amazon | Nova Pro | $0.400 | $1.600 | $0.700 |
| 57 | Meta | Llama 3.2 90B | $0.720 | $0.720 | $0.720 |
| 58 | Meta | Llama 3.1 70B | $0.720 | $0.720 | $0.720 |
| 59 | Meta | Llama 3.3 70B | $0.720 | $0.720 | $0.720 |
| 60 | Z.AI | GLM 5 | $0.500 | $1.600 | $0.775 |
| 61 | Anthropic | Claude Instant | $0.800 | $2.400 | $0.800* |
| 62 | Meta | Llama 3.1 70B Latency Optimized | $0.900 | $0.900 | $0.900 |
| 63 | Amazon | Nova Sonic 2.0 | $0.330 | $2.750 | $0.935 |
| 64 | Mistral | Mistral Small | $1.000 | $3.000 | $1.500 |
| 65 | Amazon | Nova Pro Latency Optimized | $1.000 | $4.000 | $1.750 |
| 66 | Amazon | Nova 2.0 Pro | $0.688 | $5.500 | $1.891 |
| 67 | DeepSeek | R1 | $1.350 | $5.400 | $2.363 |
| 68 | Amazon | Nova Premier | $1.250 | $6.250 | $2.500 |
| 69 | Meta | Llama 3 70B | $2.650 | $3.500 | $2.862 |
| 70 | Mistral | Pixtral Large 25.02 | $2.000 | $6.000 | $3.000 |
| 71 | Anthropic | Claude 3 Sonnet | $3.000 | $15.000 | $3.000* |
| 72 | Mistral | Mistral Large | $4.000 | $12.000 | $6.000 |
| 73 | Anthropic | Claude 2.0 | $8.000 | $24.000 | $8.000* |
| 74 | Anthropic | Claude 2.1 | $8.000 | $24.000 | $8.000* |

\* Anthropic output rates and the **newest** Anthropic models (Haiku 4.5 ≈ $1/$5, Sonnet 4.6,
Opus 4.8) are INFERENCE_PROFILE-only and priced via the agreement rate card, not this
on-demand list — so they're under-represented above. They're the premium tier regardless.

## Notes / caveats

- **Batch** inference is ~50% of on-demand for most models. **Cross-region/"Global"** inference-
  profile rates can differ slightly from the base us-east-1 rate shown.
- Some entries are duplicated by AWS under multiple provider labels (e.g. Kimi under "Moonshot AI"
  and "Kimi AI"); both are the same model.
- "Works now" = returned a valid `converse` response under our role with no agreement/form.
  Anthropic models return `404 — use case details not submitted` until the form clears.
- **Product angle:** this is exactly the data to power a **per-model cost/quality picker** for
  users (pick by budget; show live $/1M). Pair the model list (`bedrock list-foundation-models`)
  with the Price List API and a periodic refresh.
