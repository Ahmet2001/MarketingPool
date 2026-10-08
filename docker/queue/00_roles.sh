#!/bin/sh
# Runs once, on the first start of an empty database (before the migrations).
# Gives the local queue the three roles Supabase has, so the workers' migrations and
# REST calls work unchanged: anon (nothing), service_role (bypasses row level
# security, like the real one) and authenticator (what PostgREST logs in as).
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
create role anon nologin;
create role service_role nologin bypassrls;
create role authenticator login noinherit password '${AUTHENTICATOR_PASSWORD}';
grant anon, service_role to authenticator;
grant usage on schema public to anon, service_role;
alter default privileges in schema public grant all on tables to service_role;
alter default privileges in schema public grant all on sequences to service_role;
alter default privileges in schema public grant all on functions to service_role;
SQL
