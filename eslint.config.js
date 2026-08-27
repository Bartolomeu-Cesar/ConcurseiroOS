import js from "@eslint/js";
import globals from "globals";
import prettier from "eslint-config-prettier";

export default [
  // Ignore non-frontend files
  {
    ignores: [
      "backend/**",
      "node_modules/**",
      "frontend/pdfjs/**",
      "frontend/src/**",
      "frontend/sw.js",
      "frontend/js/pages/mastery.js",
    ],
  },

  // Frontend JS files
  {
    files: ["frontend/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: {
        ...globals.browser,
        // App globals (set by app.js via Object.assign(window, ...))
        showToast: "readonly",
        showLoading: "readonly",
        showEmpty: "readonly",
        escapeHtml: "readonly",
        confirmModal: "readonly",
        launchConfetti: "readonly",
        debounce: "readonly",
        goPanel: "readonly",
        goSection: "readonly",
        toggleTheme: "readonly",
        toggleSidebar: "readonly",
        closeSidebar: "readonly",
        iniciarSessaoRapida: "readonly",
        toggleCollapse: "readonly",
      },
    },
    rules: {
      ...js.configs.recommended.rules,
      // Relaxed for existing codebase
      "no-unused-vars": ["warn", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      "no-console": "off",
      "no-undef": "warn",
      "no-empty": ["warn", { allowEmptyCatch: true }],
      "no-useless-escape": "warn",
      "no-useless-assignment": "warn",
      "no-func-assign": "warn",
      "prefer-const": "warn",
      "no-var": "warn",
      "eqeqeq": ["warn", "smart"],
      "no-duplicate-imports": "error",
    },
  },

  // Prettier compat (disables formatting rules)
  prettier,
];
