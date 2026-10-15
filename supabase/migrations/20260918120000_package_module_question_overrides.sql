-- Draft-time per-package question overrides for global modules.
-- When null, publish copies from global_modules.questions.
-- When set, publish uses this JSONB instead (does not mutate the catalog).

alter table public.package_modules
    add column if not exists questions jsonb;

comment on column public.package_modules.questions is
    'Optional draft override of global_modules.questions for this package cart row.';
