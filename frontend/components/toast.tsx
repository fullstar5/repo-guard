"use client";

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

import { cn } from "@/lib/utils";

type ToastTone = "success" | "danger";

export type ToastInput = {
  tone: ToastTone;
  message: string;
};

type ToastItem = ToastInput & { id: number };

const ToastContext = createContext<((input: ToastInput) => void) | null>(null);

export function useToast() {
  const toast = useContext(ToastContext);
  if (!toast) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return toast;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const toast = useCallback((input: ToastInput) => {
    const id = Date.now() + Math.random();
    setItems((current) => [...current.slice(-2), { id, ...input }]);
    window.setTimeout(() => {
      setItems((current) => current.filter((item) => item.id !== id));
    }, 4200);
  }, []);

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div
        className="pointer-events-none fixed right-6 bottom-6 z-[60] flex w-[min(100%-2rem,22rem)] flex-col gap-2"
        aria-live="polite"
        aria-relevant="additions"
      >
        {items.map((item) => (
          <div
            key={item.id}
            role="status"
            className={cn(
              "rounded-lg border px-3 py-2 text-sm shadow-lg",
              item.tone === "success"
                ? "border-[#166534]/80 bg-[#14532d] text-[#bbf7d0]"
                : "border-[#991b1b]/80 bg-[#7f1d1d] text-[#fecaca]",
            )}
          >
            {item.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
