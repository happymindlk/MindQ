INSERT INTO public.users (id, email, full_name, role)
VALUES (
  '513617ab-2968-47d5-91a3-0f6d612007ac',
  'happymindtesting@gmail.com',
  'Acme HR Tester',
  'client' -- or 'member'/'hr' depending on the users table role check
)
ON CONFLICT (id) DO NOTHING;