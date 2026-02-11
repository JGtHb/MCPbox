import { useMemo } from 'react'
import { useCopyToClipboard } from '../../hooks/useCopyToClipboard'

interface CodePreviewProps {
  code: string
  language?: string
  title?: string
}

// Token types for syntax highlighting
type TokenType = 'keyword' | 'string' | 'comment' | 'decorator' | 'number' | 'function' | 'text'

interface Token {
  type: TokenType
  value: string
}

// Token type to Tailwind class mapping
const TOKEN_CLASSES: Record<TokenType, string> = {
  keyword: 'text-purple-400',
  string: 'text-green-400',
  comment: 'text-gray-500',
  decorator: 'text-yellow-400',
  number: 'text-orange-400',
  function: 'text-blue-400',
  text: 'text-gray-300',
}

export function CodePreview({ code, language = 'python', title }: CodePreviewProps) {
  const { copied, copy } = useCopyToClipboard()

  const handleCopy = () => {
    copy(code)
  }

  // Memoize tokenization to avoid re-processing on every render
  const tokens = useMemo(() => tokenizePython(code), [code])

  return (
    <div className="bg-gray-900 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700">
        <div className="flex items-center space-x-3">
          {title && <span className="text-sm font-medium text-gray-300">{title}</span>}
          <span className="px-2 py-0.5 text-xs bg-gray-700 text-gray-400 rounded">
            {language}
          </span>
        </div>
        <button
          onClick={handleCopy}
          className="flex items-center space-x-1 px-3 py-1 text-sm text-gray-400 hover:text-gray-200 hover:bg-gray-700 rounded transition-colors"
          aria-label={copied ? 'Code copied to clipboard' : 'Copy code to clipboard'}
        >
          {copied ? (
            <>
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              <span>Copied!</span>
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
                />
              </svg>
              <span>Copy</span>
            </>
          )}
        </button>
      </div>

      {/* Code - using React elements instead of dangerouslySetInnerHTML */}
      <div className="overflow-auto max-h-[600px]">
        <pre className="p-4 text-sm font-mono leading-relaxed">
          <code className="text-gray-300">
            {tokens.map((token, index) => (
              <span key={index} className={TOKEN_CLASSES[token.type]}>
                {token.value}
              </span>
            ))}
          </code>
        </pre>
      </div>
    </div>
  )
}

// Python keywords
const PYTHON_KEYWORDS = new Set([
  'from', 'import', 'async', 'await', 'def', 'class', 'if', 'else', 'elif',
  'for', 'while', 'return', 'try', 'except', 'finally', 'with', 'as', 'None',
  'True', 'False', 'and', 'or', 'not', 'in', 'is', 'lambda', 'pass', 'break',
  'continue', 'raise', 'yield', 'global', 'nonlocal',
])

/**
 * Tokenize Python code into typed tokens for safe rendering.
 * This approach avoids dangerouslySetInnerHTML by creating React-safe tokens.
 */
function tokenizePython(code: string): Token[] {
  const tokens: Token[] = []
  let i = 0

  while (i < code.length) {
    // Check for triple-quoted strings (must check before single quotes)
    if (code.slice(i, i + 3) === '"""' || code.slice(i, i + 3) === "'''") {
      const quote = code.slice(i, i + 3)
      const startWithF = i > 0 && code[i - 1].toLowerCase() === 'f'
      const start = startWithF ? i - 1 : i

      // If we captured an 'f' in the previous text token, remove it
      if (startWithF && tokens.length > 0 && tokens[tokens.length - 1].type === 'text') {
        const lastToken = tokens[tokens.length - 1]
        if (lastToken.value.endsWith('f')) {
          lastToken.value = lastToken.value.slice(0, -1)
          if (lastToken.value.length === 0) {
            tokens.pop()
          }
        }
      }

      const end = code.indexOf(quote, i + 3)
      if (end !== -1) {
        tokens.push({ type: 'string', value: code.slice(start, end + 3) })
        i = end + 3
        continue
      }
    }

    // Check for single/double quoted strings
    if (code[i] === '"' || code[i] === "'") {
      const quote = code[i]
      const startWithF = i > 0 && code[i - 1].toLowerCase() === 'f'
      const start = startWithF ? i - 1 : i

      // If we captured an 'f' in the previous text token, remove it
      if (startWithF && tokens.length > 0 && tokens[tokens.length - 1].type === 'text') {
        const lastToken = tokens[tokens.length - 1]
        if (lastToken.value.endsWith('f')) {
          lastToken.value = lastToken.value.slice(0, -1)
          if (lastToken.value.length === 0) {
            tokens.pop()
          }
        }
      }

      let j = i + 1
      while (j < code.length && code[j] !== quote && code[j] !== '\n') {
        if (code[j] === '\\' && j + 1 < code.length) j++
        j++
      }
      if (j < code.length && code[j] === quote) {
        tokens.push({ type: 'string', value: code.slice(start, j + 1) })
        i = j + 1
        continue
      }
    }

    // Check for comments
    if (code[i] === '#') {
      const end = code.indexOf('\n', i)
      if (end !== -1) {
        tokens.push({ type: 'comment', value: code.slice(i, end) })
        i = end
        continue
      } else {
        tokens.push({ type: 'comment', value: code.slice(i) })
        break
      }
    }

    // Check for decorators
    if (code[i] === '@' && (i === 0 || /[\s\n]/.test(code[i - 1]))) {
      let j = i + 1
      while (j < code.length && /[\w.]/.test(code[j])) j++
      // Include parentheses if present
      if (j < code.length && code[j] === '(') {
        let depth = 1
        j++
        while (j < code.length && depth > 0) {
          if (code[j] === '(') depth++
          else if (code[j] === ')') depth--
          j++
        }
      }
      tokens.push({ type: 'decorator', value: code.slice(i, j) })
      i = j
      continue
    }

    // Check for numbers
    if (/\d/.test(code[i]) && (i === 0 || !/\w/.test(code[i - 1]))) {
      let j = i
      while (j < code.length && /[\d.]/.test(code[j])) j++
      tokens.push({ type: 'number', value: code.slice(i, j) })
      i = j
      continue
    }

    // Check for words (keywords, identifiers)
    if (/[a-zA-Z_]/.test(code[i])) {
      let j = i
      while (j < code.length && /\w/.test(code[j])) j++
      const word = code.slice(i, j)

      // Check if this is a function definition
      if (word === 'def' && j < code.length) {
        tokens.push({ type: 'keyword', value: word })
        i = j

        // Skip whitespace and capture function name
        while (i < code.length && /\s/.test(code[i])) {
          tokens.push({ type: 'text', value: code[i] })
          i++
        }

        // Capture function name
        if (i < code.length && /[a-zA-Z_]/.test(code[i])) {
          let k = i
          while (k < code.length && /\w/.test(code[k])) k++
          tokens.push({ type: 'function', value: code.slice(i, k) })
          i = k
        }
        continue
      }

      if (PYTHON_KEYWORDS.has(word)) {
        tokens.push({ type: 'keyword', value: word })
      } else {
        tokens.push({ type: 'text', value: word })
      }
      i = j
      continue
    }

    // Default: add as text
    // Batch consecutive non-special characters
    let j = i
    while (j < code.length &&
           !/[a-zA-Z_\d"'#@]/.test(code[j]) &&
           !(code.slice(j, j + 3) === '"""') &&
           !(code.slice(j, j + 3) === "'''")) {
      j++
    }
    if (j > i) {
      tokens.push({ type: 'text', value: code.slice(i, j) })
      i = j
    } else {
      tokens.push({ type: 'text', value: code[i] })
      i++
    }
  }

  return tokens
}
