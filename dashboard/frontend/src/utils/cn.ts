/**
 * Class name utility — combines clsx (conditional classes) with
 * tailwind-merge (deduplicates conflicting Tailwind utility classes).
 *
 * Usage:
 *   cn('px-4 py-2', isActive && 'bg-blue-600', className)
 */
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
