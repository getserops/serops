import globals from "globals";
import pluginJs from "@eslint/js";
import pluginReact from "eslint-plugin-react";
import pluginReactHooks from "eslint-plugin-react-hooks";

export default [
    // Ignore patterns
    {
        ignores: ["build/**", "node_modules/**", "dist/**"]
    },

    // Base configuration for all JS/JSX files
    {
        files: ["**/*.{js,jsx}"],
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: "module",
            globals: {
                ...globals.browser,
                ...globals.node,
                ...globals.es2021
            },
            parserOptions: {
                ecmaFeatures: {
                    jsx: true
                }
            }
        },
        plugins: {
            react: pluginReact,
            "react-hooks": pluginReactHooks
        },
        rules: {
            // ESLint recommended rules (relaxed for existing codebase)
            ...pluginJs.configs.recommended.rules,

            // React rules
            "react/react-in-jsx-scope": "off", // Not needed in React 17+
            "react/prop-types": "off", // Disable prop-types (consider TypeScript instead)
            "react/jsx-uses-react": "error",
            "react/jsx-uses-vars": "error",

            // React Hooks rules
            "react-hooks/rules-of-hooks": "error",
            "react-hooks/exhaustive-deps": "warn",

            // Relaxed rules to avoid breaking existing code
            "no-unused-vars": ["warn", {
                "argsIgnorePattern": "^_",
                "varsIgnorePattern": "^_"
            }],
            "no-console": "off", // Allow console for now
            "no-undef": "error",
            "no-empty": "warn",
            "no-constant-condition": "warn",

            // Code quality
            "eqeqeq": ["warn", "smart"],
            "no-duplicate-imports": "error"
        },
        settings: {
            react: {
                version: "detect"
            }
        }
    }
];
