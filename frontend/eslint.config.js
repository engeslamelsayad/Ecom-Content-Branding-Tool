// The build passing is not enough: Vite happily bundles an undefined
// identifier as a global, so a missing `import { Globe }` ships as a runtime
// ReferenceError and a blank page. `no-undef` is what actually catches that,
// which is why lint runs before every build.
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import react from 'eslint-plugin-react'

export default [
  { ignores: ['dist/**', 'node_modules/**'] },
  {
    files: ['**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: 'module',
      globals: { ...globals.browser },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { 'react-hooks': reactHooks, react },
    settings: { react: { version: 'detect' } },
    rules: {
      ...js.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      'no-undef': 'error',
      // no-undef does not follow component names in JSX — this is the rule
      // that catches `<Globe />` with no matching import.
      'react/jsx-no-undef': 'error',
      'react/jsx-uses-vars': 'error',
      'no-unused-vars': ['warn', { varsIgnorePattern: '^[A-Z_]', args: 'none' }],
      'react-hooks/exhaustive-deps': 'off',
    },
  },
]
