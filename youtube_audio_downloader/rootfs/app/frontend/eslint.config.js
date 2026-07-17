import eslint from "@eslint/js";
import globals from "globals";
import lit from "eslint-plugin-lit";
import tseslint from "typescript-eslint";

export default tseslint.config(
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  lit.configs["flat/recommended"],
  {
    files: ["src/**/*.ts"],
    languageOptions: { globals: globals.browser },
    rules: {
      "@typescript-eslint/no-explicit-any": "off"
    }
  }
);
