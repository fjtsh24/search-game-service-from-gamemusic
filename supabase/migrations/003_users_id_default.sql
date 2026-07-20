-- users.id に DEFAULT gen_random_uuid() を追加
-- Steam OpenID 認証では Supabase Auth を経由しないため、API 側で UUID を生成する
ALTER TABLE users ALTER COLUMN id SET DEFAULT gen_random_uuid();
