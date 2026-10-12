import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** shadcn/ui 的类名合并约定（复制式组件的公共依赖） */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
