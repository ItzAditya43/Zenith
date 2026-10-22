import { createContext, useContext } from "react";

/** Everything SettingsPanel owns (config, per-section state, handlers),
 * shared with the section components in this folder. The panel is still the
 * single owner of state — sections are presentational slices of it. */
export const SettingsContext = createContext(null);

export function useSettings() {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error("useSettings() must be used inside <SettingsPanel>.");
  return ctx;
}
