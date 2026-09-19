import Link from "next/link";
import { Fragment, type ReactNode } from "react";

import { cn } from "@/lib/utils";

export type BreadcrumbItem = {
  label: string;
  href?: string;
};

export function Breadcrumbs({ items }: { items: BreadcrumbItem[] }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-5 flex flex-wrap items-center gap-2 text-sm text-[#a1a1aa]">
      {items.map((item, index) => {
        const last = index === items.length - 1;
        return (
          <Fragment key={`${item.label}-${index}`}>
            {index > 0 ? <span className="text-[#3f3f46]">/</span> : null}
            {item.href && !last ? (
              <Link
                href={item.href}
                title={item.label}
                className="max-w-[16rem] truncate rounded-sm hover:text-[#fafafa] focus-visible:text-[#fafafa] focus-visible:ring-2 focus-visible:ring-[#22d3ee]/70 focus-visible:outline-none"
              >
                {item.label}
              </Link>
            ) : (
              <span
                title={item.label}
                className={cn(
                  "max-w-[16rem] truncate",
                  last ? "font-medium text-[#fafafa]" : undefined,
                )}
              >
                {item.label}
              </span>
            )}
          </Fragment>
        );
      })}
    </nav>
  );
}

export function PageToolbar({
  title,
  meta,
  action,
  className,
}: {
  title: string;
  meta?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mb-6 flex items-center justify-between gap-4", className)}>
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-[#fafafa]">{title}</h1>
        {meta ? <p className="mt-1 text-sm text-[#a1a1aa]">{meta}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function FilterBar({ children }: { children: ReactNode }) {
  return <div className="mb-5 flex flex-wrap items-center gap-3">{children}</div>;
}

export function SearchInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <label className="relative block w-full max-w-sm">
      <span className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-[#a1a1aa]">
        <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-3-3" />
        </svg>
      </span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className="h-9 w-full rounded-lg border border-[#3f3f46] bg-[#09090b] pr-3 pl-9 text-sm text-[#fafafa] placeholder:text-[#a1a1aa] outline-none focus:border-[#22d3ee]/60 focus-visible:ring-2 focus-visible:ring-[#22d3ee]/50"
      />
    </label>
  );
}

export function FilterSelect({
  value,
  onChange,
  options,
  "aria-label": ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
  "aria-label"?: string;
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      aria-label={ariaLabel}
      className="h-9 rounded-lg border border-[#3f3f46] bg-[#18181b] px-3 text-sm text-[#fafafa] outline-none focus:border-[#22d3ee]/60 focus-visible:ring-2 focus-visible:ring-[#22d3ee]/50"
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
