// 骨架屏。带 shimmer 高光扫描动效。
export default function Skeleton({ className = '', rounded = 'rounded-md', ...rest }) {
  return (
    <div
      className={`relative overflow-hidden bg-surface-container-high ${rounded} ${className}`}
      {...rest}
    >
      <div className="absolute inset-0 -translate-x-full animate-shimmer-strip bg-gradient-to-r from-transparent via-white/55 to-transparent" />
    </div>
  )
}

export function SkeletonText({ lines = 3, className = '' }) {
  return (
    <div className={`flex flex-col gap-2 ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={`h-3 ${i === lines - 1 ? 'w-2/3' : 'w-full'}`}
        />
      ))}
    </div>
  )
}

export function SkeletonCard({ className = '' }) {
  return (
    <div className={`p-4 rounded-xl border border-outline-variant/40 bg-white ${className}`}>
      <Skeleton className="h-4 w-1/3 mb-3" />
      <SkeletonText lines={2} />
      <div className="flex gap-2 mt-4">
        <Skeleton className="h-6 w-16" rounded="rounded-full" />
        <Skeleton className="h-6 w-20" rounded="rounded-full" />
      </div>
    </div>
  )
}
