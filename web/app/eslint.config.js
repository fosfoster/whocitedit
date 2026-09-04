import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";

// `reactHooks.configs["recommended-latest"]` is the flat-config entry. In v6 the
// plugin also still exports a legacy `recommended` whose shape is the old
// eslintrc one -- reaching for `.rules` off that yields undefined and eslint
// fails the whole run with `Key "rules": Expected an object`, which reads like a
// broken config file rather than a wrong key.
export default tseslint.config(
  { ignores: ["dist", "../assets/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  reactHooks.configs["recommended-latest"],
  { files: ["src/**/*.{ts,tsx}"] },
);
