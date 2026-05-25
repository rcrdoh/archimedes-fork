/**
 * Lightweight LaTeX-to-text preprocessor for paper titles and abstracts.
 *
 * Converts common LaTeX constructs to Unicode/HTML equivalents without
 * pulling in a full KaTeX dependency. Handles the most frequent patterns
 * found in arXiv q-fin paper metadata (Issue #337).
 *
 * Falls back gracefully: if a LaTeX pattern is unrecognized, strips the
 * delimiters and shows the raw content in monospace rather than rendering
 * broken dollar-sign literals.
 */

// Common LaTeX commands → Unicode replacements
const COMMAND_MAP = {
  '\\alpha': 'α', '\\beta': 'β', '\\gamma': 'γ', '\\delta': 'δ',
  '\\epsilon': 'ε', '\\zeta': 'ζ', '\\eta': 'η', '\\theta': 'θ',
  '\\iota': 'ι', '\\kappa': 'κ', '\\lambda': 'λ', '\\mu': 'μ',
  '\\nu': 'ν', '\\xi': 'ξ', '\\pi': 'π', '\\rho': 'ρ',
  '\\sigma': 'σ', '\\tau': 'τ', '\\phi': 'φ', '\\chi': 'χ',
  '\\psi': 'ψ', '\\omega': 'ω',
  '\\Gamma': 'Γ', '\\Delta': 'Δ', '\\Theta': 'Θ', '\\Lambda': 'Λ',
  '\\Sigma': 'Σ', '\\Phi': 'Φ', '\\Psi': 'Ψ', '\\Omega': 'Ω',
  '\\infty': '∞', '\\partial': '∂', '\\nabla': '∇',
  '\\sim': '∼', '\\approx': '≈', '\\neq': '≠', '\\leq': '≤', '\\geq': '≥',
  '\\times': '×', '\\cdot': '·', '\\pm': '±', '\\mp': '∓',
  '\\in': '∈', '\\notin': '∉', '\\subset': '⊂', '\\supset': '⊃',
  '\\cup': '∪', '\\cap': '∩', '\\forall': '∀', '\\exists': '∃',
  '\\rightarrow': '→', '\\leftarrow': '←', '\\Rightarrow': '⇒',
  '\\ell': 'ℓ', '\\hbar': 'ℏ',
  '\\%': '%', '\\$': '$', '\\&': '&',
  '\\!': '', '\\,': ' ', '\\;': ' ', '\\:': ' ', '\\quad': '  ',
}

/**
 * Strip LaTeX formatting commands that have a single braced argument,
 * keeping the content: \textbf{x} → x, \emph{y} → y, etc.
 */
function stripBracedCommands(text) {
  // \boldsymbol{x}, \mathbf{x}, \mathrm{x}, \mathcal{x}, \textbf{x},
  // \textit{x}, \emph{x}, \text{x}, \operatorname{x}, \hat{x}, \tilde{x}, \bar{x}
  return text.replace(
    /\\(?:boldsymbol|mathbf|mathrm|mathcal|mathbb|mathit|textbf|textit|emph|text|operatorname|hat|tilde|bar|overline|underline|vec)\{([^}]*)\}/g,
    '$1'
  )
}

/**
 * Convert LaTeX superscripts and subscripts to Unicode where possible.
 */
function convertScripts(text) {
  // Simple single-char superscripts: ^{2} → ², ^{n} → ⁿ
  const superMap = { '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
    '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
    'n': 'ⁿ', 'i': 'ⁱ', '+': '⁺', '-': '⁻', '(': '⁽', ')': '⁾' }
  text = text.replace(/\^{([^}])}/g, (_, c) => superMap[c] || `^${c}`)
  text = text.replace(/\^([0-9])/g, (_, c) => superMap[c] || `^${c}`)

  // Simple subscripts: _{0} → ₀
  const subMap = { '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄',
    '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉',
    'i': 'ᵢ', 'j': 'ⱼ', 'n': 'ₙ', '+': '₊', '-': '₋' }
  text = text.replace(/_{([^}])}/g, (_, c) => subMap[c] || `_${c}`)

  return text
}

/**
 * Process a text string containing LaTeX, returning a cleaned version.
 *
 * @param {string} text — raw text possibly containing LaTeX
 * @returns {string} — cleaned text with LaTeX converted to Unicode
 */
export function cleanLatex(text) {
  if (!text || typeof text !== 'string') return text || ''

  // Quick check: if no LaTeX indicators, return as-is (fast path)
  if (!text.includes('\\') && !text.includes('$') && !text.includes('^') && !text.includes('_')) {
    return text
  }

  let result = text

  // 1. Strip dollar-sign math delimiters: $x$ → x, $$x$$ → x
  result = result.replace(/\$\$([^$]+)\$\$/g, '$1')
  result = result.replace(/\$([^$]+)\$/g, '$1')

  // 2. Strip braced formatting commands (keep content)
  result = stripBracedCommands(result)

  // 3. Replace known LaTeX commands with Unicode
  for (const [cmd, replacement] of Object.entries(COMMAND_MAP)) {
    // Escape backslash for regex, match command boundary
    const escaped = cmd.replace(/\\/g, '\\\\')
    result = result.replace(new RegExp(escaped + '(?![a-zA-Z])', 'g'), replacement)
  }

  // 4. Convert super/subscripts
  result = convertScripts(result)

  // 5. Clean up remaining LaTeX artifacts
  result = result.replace(/\{([^}]*)\}/g, '$1')  // Remove remaining braces
  result = result.replace(/\\\\/g, ' ')            // \\ newlines → space
  result = result.replace(/\\[a-zA-Z]+/g, '')      // Strip any remaining unknown commands

  // 6. Normalize whitespace
  result = result.replace(/\s+/g, ' ').trim()

  return result
}
