import { createContext, useContext, type JSX, type Accessor } from "solid-js";

/**
 * Create a typed context with a custom hook.
 * Throws an error if used outside the provider.
 */
export function createContextHelper<T>(name: string) {
  const Context = createContext<T>();

  function useContextValue(): T {
    const value = useContext(Context);
    if (value === undefined) {
      throw new Error(`use${name} must be used within a ${name}Provider`);
    }
    return value;
  }

  return [Context.Provider, useContextValue] as const;
}
