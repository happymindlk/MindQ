INSERT INTO hr_users (user_id, corporate_id, full_name, role)
VALUES (
  '513617ab-2968-47d5-91a3-0f6d612007ac',
  (SELECT id FROM corporates WHERE slug = 'acme-corp'),
  'Acme HR Tester',
  'hr'
);