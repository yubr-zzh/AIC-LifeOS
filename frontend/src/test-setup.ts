// 给 jsdom 补 CSS.supports()：react-activity-calendar 在 validateThemeInput 里调用，
// jsdom 默认没实现这个方法，会抛 "Cannot read properties of undefined (reading 'supports')"。
if (typeof CSS === "undefined" || typeof CSS.supports !== "function") {
  globalThis.CSS = {
    ...(globalThis.CSS ?? {}),
    supports: () => true,
  } as typeof CSS;
}

// react-activity-calendar 启动时会调 window.matchMedia，jsdom 没实现。
if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
}
