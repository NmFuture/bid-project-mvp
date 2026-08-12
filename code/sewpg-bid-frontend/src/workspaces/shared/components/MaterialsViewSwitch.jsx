import { NavLink } from 'react-router-dom'

// 素材库统一页头：按工作组分区渲染（如「技术标」「共享」），
// 各组徽标与 tab 常驻并列，跨页跳转不再整段替换，避免 tab 条闪变。
// groups: [{ key, label, icon, items: [{ key, label, to }] }]，to 为绝对路径。
export default function MaterialsViewSwitch({
  active = '',
  title = '',
  subtitle = '',
  actions = null,
  meta = null,
  groups = [],
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-outline-variant/45 bg-surface-container-lowest">
      <div className="flex min-h-[72px] flex-col gap-3 px-4 py-3 lg:flex-row lg:items-center lg:justify-between lg:px-5">
        <div className="flex min-w-0 flex-1 flex-col gap-3 lg:flex-row lg:items-center">
          <div className="min-w-0 lg:w-[240px] xl:w-[260px]">
            <div className="flex min-w-0 items-center gap-2">
              <h1 className="truncate text-2xl font-headline font-semibold text-on-surface">{title || '素材库'}</h1>
            </div>
            {subtitle ? (
              <p className="mt-1 truncate text-sm text-on-surface-variant" title={typeof subtitle === 'string' ? subtitle : undefined}>
                {subtitle}
              </p>
            ) : null}
          </div>

          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
            {groups.map((group, groupIndex) => (
              <div key={group.key} className="flex min-w-0 flex-wrap items-center gap-2">
                {groupIndex > 0 ? (
                  <span aria-hidden="true" className="hidden h-6 w-px bg-outline-variant/60 sm:inline-block" />
                ) : null}
                <span className="inline-flex h-8 items-center gap-1.5 px-1 text-xs font-semibold text-on-surface">
                  <span aria-hidden="true" className="material-symbols-outlined text-[16px]">{group.icon}</span>
                  {group.label}
                </span>
                <div className="inline-flex h-8 w-fit rounded-md border border-outline-variant bg-white p-0.5 text-xs">
                  {(group.items || []).map((item) => {
                    const selected = active === item.key
                    return (
                      <NavLink
                        key={item.key}
                        to={item.to}
                        className={`inline-flex h-7 min-w-[74px] items-center justify-center rounded-md px-2.5 transition-colors ${
                          selected
                            ? 'bg-surface-container-high font-semibold text-on-surface'
                            : 'text-on-surface-variant hover:bg-surface-container-high'
                        }`}
                      >
                        {item.label}
                      </NavLink>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="flex min-h-9 min-w-[12rem] shrink-0 items-center justify-start lg:justify-end">
          {actions}
        </div>
      </div>

      {meta ? (
        <div className="border-t border-surface-container-high bg-surface-container-lowest/80 px-4 py-2 lg:px-5">
          <div className="flex min-h-7 min-w-0 items-center overflow-x-auto">
            {meta}
          </div>
        </div>
      ) : null}
    </div>
  )
}
