-- ---------------------------------------------------------------------------
-- Portable RLS isolation assertions (run with psql -v ON_ERROR_STOP=1).
-- Any failed assertion raises an exception, which fails the run.
-- Prereqs: _local_shim.sql + all non-storage migrations applied to a fresh DB.
-- ---------------------------------------------------------------------------

-- Seed two tenants (as the privileged bootstrap role).
insert into public.corporates (id, name, slug) values
  ('22222222-2222-2222-2222-222222222222', 'Acme', 'acme'),
  ('33333333-3333-3333-3333-333333333333', 'Beta', 'beta');
insert into public.packages (id, corporate_id, title, access_code) values
  ('aaaaaaaa-0000-0000-0000-000000000001', '22222222-2222-2222-2222-222222222222', 'Acme Pkg', 'HM-AAAAAA-1'),
  ('bbbbbbbb-0000-0000-0000-000000000002', '33333333-3333-3333-3333-333333333333', 'Beta Pkg', 'HM-BBBBBB-2');

-- Act as an authenticated HR user of tenant A.
set role authenticated;
select set_config(
  'request.jwt.claims',
  '{"sub":"11111111-1111-1111-1111-111111111111","app_metadata":{"corporate_id":"22222222-2222-2222-2222-222222222222"}}',
  false
);

-- 1) SELECT isolation: tenant A sees only its own package.
do $$
begin
  if (select count(*) from public.packages) <> 1 then
    raise exception 'RLS SELECT: expected 1 visible package, got %', (select count(*) from public.packages);
  end if;
  if not exists (select 1 from public.packages where corporate_id = '22222222-2222-2222-2222-222222222222') then
    raise exception 'RLS SELECT: tenant A cannot see its own package';
  end if;
end $$;

-- 2) INSERT WITH CHECK: creating a row for another tenant is blocked.
do $$
begin
  begin
    insert into public.packages (corporate_id, title, access_code)
    values ('33333333-3333-3333-3333-333333333333', 'Cross', 'HM-CCCCCC-3');
    raise exception 'RLS INSERT: cross-tenant insert unexpectedly succeeded';
  exception
    when insufficient_privilege then null;  -- expected: WITH CHECK violation
  end;
end $$;

-- 3) UPDATE isolation: updating another tenant's row affects 0 rows.
do $$
declare n int;
begin
  update public.packages set title = 'HACKED'
   where id = 'bbbbbbbb-0000-0000-0000-000000000002';
  get diagnostics n = row_count;
  if n <> 0 then
    raise exception 'RLS UPDATE: cross-tenant update affected % rows (expected 0)', n;
  end if;
end $$;

reset role;

-- 4) service_role bypasses RLS: sees both tenants' packages.
set role service_role;
do $$
begin
  if (select count(*) from public.packages) < 2 then
    raise exception 'service_role should see all packages, got %', (select count(*) from public.packages);
  end if;
end $$;
reset role;

-- 5) HR (authenticated) cannot write scores or responses. Seed as the
-- privileged role, then attempt UPDATE/INSERT as the tenant.
insert into public.assessments (id, corporate_id, package_id, title, questions)
values (
  'cccccccc-0000-0000-0000-000000000003',
  '22222222-2222-2222-2222-222222222222',
  'aaaaaaaa-0000-0000-0000-000000000001',
  'Acme Test',
  '[]'::jsonb
);
insert into public.candidates (id, corporate_id, package_id, full_name, email, access_code)
values (
  'dddddddd-0000-0000-0000-000000000004',
  '22222222-2222-2222-2222-222222222222',
  'aaaaaaaa-0000-0000-0000-000000000001',
  'Pat Candidate',
  'pat@acme.test',
  'HM-AAAAAA-1'
);
insert into public.candidate_progress (id, corporate_id, candidate_id, assessment_id, status, score)
values (
  'eeeeeeee-0000-0000-0000-000000000005',
  '22222222-2222-2222-2222-222222222222',
  'dddddddd-0000-0000-0000-000000000004',
  'cccccccc-0000-0000-0000-000000000003',
  'COMPLETED',
  42.00
);
insert into public.candidate_responses (id, corporate_id, candidate_id, assessment_id, question_id, response)
values (
  'ffffffff-0000-0000-0000-000000000006',
  '22222222-2222-2222-2222-222222222222',
  'dddddddd-0000-0000-0000-000000000004',
  'cccccccc-0000-0000-0000-000000000003',
  'q1',
  '{"answer": "4"}'::jsonb
);

set role authenticated;
select set_config(
  'request.jwt.claims',
  '{"sub":"11111111-1111-1111-1111-111111111111","app_metadata":{"corporate_id":"22222222-2222-2222-2222-222222222222"}}',
  false
);

do $$
begin
  begin
    update public.candidate_progress set score = 100
     where id = 'eeeeeeee-0000-0000-0000-000000000005';
    raise exception 'HR UPDATE on candidate_progress unexpectedly succeeded';
  exception
    when insufficient_privilege then null;
  end;

  begin
    insert into public.candidate_progress (corporate_id, candidate_id, assessment_id, status, score)
    values (
      '22222222-2222-2222-2222-222222222222',
      'dddddddd-0000-0000-0000-000000000004',
      'cccccccc-0000-0000-0000-000000000003',
      'COMPLETED',
      99.00
    );
    raise exception 'HR INSERT on candidate_progress unexpectedly succeeded';
  exception
    when insufficient_privilege then null;
  end;

  begin
    update public.candidate_responses set response = '{"answer": "hacked"}'::jsonb
     where id = 'ffffffff-0000-0000-0000-000000000006';
    raise exception 'HR UPDATE on candidate_responses unexpectedly succeeded';
  exception
    when insufficient_privilege then null;
  end;

  begin
    insert into public.candidate_responses (corporate_id, candidate_id, assessment_id, question_id, response)
    values (
      '22222222-2222-2222-2222-222222222222',
      'dddddddd-0000-0000-0000-000000000004',
      'cccccccc-0000-0000-0000-000000000003',
      'q2',
      '{"answer": "hacked"}'::jsonb
    );
    raise exception 'HR INSERT on candidate_responses unexpectedly succeeded';
  exception
    when insufficient_privilege then null;
  end;
end $$;

reset role;

-- 6) service_role remains the writer of scores.
set role service_role;
do $$
declare n int;
begin
  update public.candidate_progress set score = 43.00
   where id = 'eeeeeeee-0000-0000-0000-000000000005';
  get diagnostics n = row_count;
  if n <> 1 then
    raise exception 'service_role should update candidate_progress, affected % rows', n;
  end if;
end $$;
reset role;

-- 7) HR cannot write JD evaluations; SELECT of own tenant is allowed.
insert into public.candidate_evaluations (
  id, corporate_id, candidate_id, package_id, jd_hash, model, overall_fit, payload
) values (
  'aaaaaaaa-1111-0000-0000-000000000007',
  '22222222-2222-2222-2222-222222222222',
  'dddddddd-0000-0000-0000-000000000004',
  'aaaaaaaa-0000-0000-0000-000000000001',
  'abc',
  'gemini-2.5-flash',
  71.00,
  '{"overall_fit":71,"summary":"ok","strengths":[],"gaps":[],"per_assessment":[]}'::jsonb
);

set role authenticated;
select set_config(
  'request.jwt.claims',
  '{"sub":"11111111-1111-1111-1111-111111111111","app_metadata":{"corporate_id":"22222222-2222-2222-2222-222222222222"}}',
  false
);

do $$
begin
  if (select count(*) from public.candidate_evaluations) <> 1 then
    raise exception 'HR SELECT: expected 1 JD evaluation, got %', (select count(*) from public.candidate_evaluations);
  end if;

  begin
    update public.candidate_evaluations set overall_fit = 100
     where id = 'aaaaaaaa-1111-0000-0000-000000000007';
    raise exception 'HR UPDATE on candidate_evaluations unexpectedly succeeded';
  exception
    when insufficient_privilege then null;
  end;

  begin
    insert into public.candidate_evaluations (
      corporate_id, candidate_id, package_id, jd_hash, model, overall_fit, payload
    ) values (
      '22222222-2222-2222-2222-222222222222',
      'dddddddd-0000-0000-0000-000000000004',
      'aaaaaaaa-0000-0000-0000-000000000001',
      'def',
      'gemini-2.5-flash',
      99.00,
      '{}'::jsonb
    );
    raise exception 'HR INSERT on candidate_evaluations unexpectedly succeeded';
  exception
    when insufficient_privilege then null;
  end;
end $$;
reset role;

-- 8) HR cannot see psychometric assessment snapshots (integrity).
insert into public.assessments (
  id, corporate_id, package_id, title, questions, module_kind
) values (
  'cccccccc-0000-0000-0000-000000000099',
  '22222222-2222-2222-2222-222222222222',
  'aaaaaaaa-0000-0000-0000-000000000001',
  'Hidden Psychometric',
  '[{"id":"p1","text":"secret item"}]'::jsonb,
  'psychometric'
);

set role authenticated;
select set_config(
  'request.jwt.claims',
  '{"sub":"11111111-1111-1111-1111-111111111111","app_metadata":{"corporate_id":"22222222-2222-2222-2222-222222222222","corporate_role":"hr"}}',
  false
);

do $$
begin
  if exists (
    select 1 from public.assessments
     where id = 'cccccccc-0000-0000-0000-000000000099'
  ) then
    raise exception 'HR SELECT: psychometric assessment leaked';
  end if;
  if not exists (
    select 1 from public.assessments
     where id = 'cccccccc-0000-0000-0000-000000000003'
  ) then
    raise exception 'HR SELECT: technical assessment should remain visible';
  end if;
  if (select count(*) from public.global_modules) <> 0 then
    raise exception 'HR SELECT: global_modules catalog leaked, got %',
      (select count(*) from public.global_modules);
  end if;
end $$;
reset role;

-- 8b) HR cannot SELECT psychometric candidate_responses (answers leak item content).
insert into public.candidate_responses (
  id, corporate_id, candidate_id, assessment_id, question_id, response
) values (
  'ffffffff-0000-0000-0000-000000000099',
  '22222222-2222-2222-2222-222222222222',
  'dddddddd-0000-0000-0000-000000000004',
  'cccccccc-0000-0000-0000-000000000099',
  'p1',
  '{"answer": "psychometric secret"}'::jsonb
);

set role authenticated;
select set_config(
  'request.jwt.claims',
  '{"sub":"11111111-1111-1111-1111-111111111111","app_metadata":{"corporate_id":"22222222-2222-2222-2222-222222222222","corporate_role":"hr"}}',
  false
);

do $$
begin
  if exists (
    select 1 from public.candidate_responses
     where id = 'ffffffff-0000-0000-0000-000000000099'
  ) then
    raise exception 'HR SELECT: psychometric response leaked';
  end if;
  if not exists (
    select 1 from public.candidate_responses
     where id = 'ffffffff-0000-0000-0000-000000000006'
  ) then
    raise exception 'HR SELECT: technical response should remain visible';
  end if;
end $$;
reset role;

-- 9) Ops JWT can read global_modules and all corporates.
set role authenticated;
select set_config(
  'request.jwt.claims',
  '{"sub":"11111111-1111-1111-1111-111111111111","app_metadata":{"corporate_id":"22222222-2222-2222-2222-222222222222","corporate_role":"admin"}}',
  false
);

do $$
begin
  if (select count(*) from public.corporates) < 2 then
    raise exception 'Ops SELECT: expected all corporates, got %', (select count(*) from public.corporates);
  end if;
  if (select count(*) from public.global_modules) < 6 then
    raise exception 'Ops SELECT: expected seeded global modules, got %',
      (select count(*) from public.global_modules);
  end if;
end $$;
reset role;

select 'RLS assertions passed' as result;
