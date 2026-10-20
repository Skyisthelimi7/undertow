-- Undertow community: rug calls, votes and crowd tags.
-- Run once in Supabase: Dashboard -> SQL Editor -> New query -> paste this file -> Run. Safe to run again.
--
-- Who can do what
--   Anyone can read the leaderboard, settled calls and each token's counts.
--   Signed-in visitors act only through the four functions at the bottom (pick a name, call, vote, tag), which
--   enforce the rules: a public name first, calls only on tokens the screener lists, one open call per token,
--   ten calls a day, no cancelling. There are no insert, update or delete policies, so nothing else gets in.
--   The scanner (GitHub Actions, holding the secret key) lists the tokens and prices and settles the calls.

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  name text not null unique check (name ~ '^[A-Za-z0-9_]{3,20}$'),
  created_at timestamptz not null default now()
);
create unique index if not exists profiles_name_any_case on public.profiles (lower(name));   -- no "Alice" beside "alice"

create table if not exists public.tokens (
  mint text primary key,
  symbol text,
  state text not null default 'OUT',          -- IN, WATCH, ENTERING or OUT, as on the page
  price double precision,
  updated_at timestamptz not null default now()
);

create table if not exists public.calls (
  id bigint generated always as identity primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  mint text not null references public.tokens(mint) on delete cascade,
  side text not null check (side in ('rug', 'hold')),
  created_at timestamptz not null default now(),
  -- filled in by the scanner
  price_at_call double precision,              -- the first scan price after the call: nobody calls with hindsight
  priced_at timestamptz,
  seen_at timestamptz,                         -- the last scan that priced the token
  hi double precision,                         -- highest and lowest multiple of the call price within the day
  lo double precision,
  up50_at timestamptz,
  dn80_at timestamptz,
  outcome text check (outcome in ('rug', 'held', 'void')),
  base_rate double precision,                  -- share of passing coins that rugged, used for the points
  points double precision,
  settled_at timestamptz
);
create unique index if not exists calls_one_open on public.calls(user_id, mint) where settled_at is null;
create index if not exists calls_open on public.calls(created_at) where settled_at is null;
create index if not exists calls_by_user on public.calls(user_id, created_at desc);
create index if not exists calls_by_mint on public.calls(mint);

create table if not exists public.votes (
  user_id uuid not null references public.profiles(id) on delete cascade,
  mint text not null references public.tokens(mint) on delete cascade,
  vote smallint not null check (vote in (-1, 1)),
  updated_at timestamptz not null default now(),
  primary key (user_id, mint)
);

create table if not exists public.tags (
  user_id uuid not null references public.profiles(id) on delete cascade,
  mint text not null references public.tokens(mint) on delete cascade,
  tag text not null check (tag in ('dev_active', 'real_community', 'cto', 'bundled', 'rug_suspected', 'fake_volume')),
  created_at timestamptz not null default now(),
  primary key (user_id, mint, tag)
);

alter table public.profiles enable row level security;
alter table public.tokens enable row level security;
alter table public.calls enable row level security;
alter table public.votes enable row level security;
alter table public.tags enable row level security;

drop policy if exists "names are public" on public.profiles;
create policy "names are public" on public.profiles for select using (true);
drop policy if exists "tokens are public" on public.tokens;
create policy "tokens are public" on public.tokens for select using (true);
drop policy if exists "settled calls are public; open ones only to their caller" on public.calls;
create policy "settled calls are public; open ones only to their caller" on public.calls for select
  using (settled_at is not null or user_id = (select auth.uid()));
drop policy if exists "own votes" on public.votes;
create policy "own votes" on public.votes for select using (user_id = (select auth.uid()));
drop policy if exists "own tags" on public.tags;
create policy "own tags" on public.tags for select using (user_id = (select auth.uid()));

-- Counts per token and the leaderboard, readable by anyone. These views run with their owner's rights so they can
-- count rows that row-level security hides from visitors; they expose names and counts, never user ids or open calls.
create or replace view public.token_crowd as
select t.mint, t.symbol,
  coalesce(c.rug, 0)::int as rug_calls, coalesce(c.hold, 0)::int as hold_calls,
  coalesce(v.up, 0)::int as watch, coalesce(v.down, 0)::int as avoid,
  coalesce(g.tags, '{}'::jsonb) as tags
from public.tokens t
left join (select mint, count(*) filter (where side = 'rug') as rug, count(*) filter (where side = 'hold') as hold
           from public.calls where settled_at is null group by mint) c on c.mint = t.mint
left join (select mint, count(*) filter (where vote = 1) as up, count(*) filter (where vote = -1) as down
           from public.votes group by mint) v on v.mint = t.mint
left join (select mint, jsonb_object_agg(tag, n) as tags
           from (select mint, tag, count(*) as n from public.tags group by mint, tag) x group by mint) g on g.mint = t.mint
where c.mint is not null or v.mint is not null or g.mint is not null;

create or replace view public.leaderboard as
select p.name,
  count(c.id) filter (where c.outcome in ('rug', 'held'))::int as settled,
  round(coalesce(sum(c.points), 0)::numeric, 1)::float8 as points,
  count(c.id) filter (where c.side = 'rug' and c.outcome = 'rug')::int as rug_right,
  count(c.id) filter (where c.side = 'rug' and c.outcome in ('rug', 'held'))::int as rug_calls,
  count(c.id) filter (where c.side = 'hold' and c.outcome = 'held')::int as hold_right,
  count(c.id) filter (where c.side = 'hold' and c.outcome in ('rug', 'held'))::int as hold_calls,
  count(c.id) filter (where c.settled_at is null)::int as open_calls,
  max(c.settled_at) as last_settled
from public.profiles p join public.calls c on c.user_id = p.id
group by p.id, p.name;

create or replace view public.recent_calls as
select c.id, p.name, c.mint, t.symbol, c.side, c.created_at, c.price_at_call, c.hi, c.lo, c.outcome, c.points,
  c.settled_at
from public.calls c join public.profiles p on p.id = c.user_id join public.tokens t on t.mint = c.mint
where c.outcome in ('rug', 'held')
order by c.settled_at desc
limit 200;

grant select on public.token_crowd, public.leaderboard, public.recent_calls to anon, authenticated;

-- The only ways a signed-in visitor can write. Each runs with the owner's rights after checking the rules.
create or replace function public.set_name(new_name text) returns text
language plpgsql security definer set search_path = public as $$
declare uid uuid := auth.uid();
begin
  if uid is null then raise exception 'Sign in first.'; end if;
  if new_name is null or new_name !~ '^[A-Za-z0-9_]{3,20}$' then
    raise exception 'Names are 3 to 20 letters, digits or underscores.';
  end if;
  if lower(new_name) ~ '(undertow|admin|moderator|official|support|staff)' or lower(new_name) in ('mod', 'team', 'system') then
    raise exception 'That name is reserved.';
  end if;
  insert into profiles(id, name) values (uid, new_name)
    on conflict (id) do update set name = excluded.name;
  return new_name;
exception when unique_violation then
  raise exception 'That name is taken.';
end $$;

create or replace function public.make_call(token text, call_side text) returns bigint
language plpgsql security definer set search_path = public as $$
declare uid uuid := auth.uid(); tok record; n int; new_id bigint;
begin
  if uid is null then raise exception 'Sign in first.'; end if;
  if not exists (select 1 from profiles where id = uid) then raise exception 'Pick a name first.'; end if;
  if call_side is null or call_side not in ('rug', 'hold') then raise exception 'A call is rug or hold.'; end if;
  select * into tok from tokens where mint = token;
  if not found or tok.state not in ('IN', 'WATCH', 'ENTERING') or tok.updated_at < now() - interval '2 hours' then
    raise exception 'Calls are open on tokens in the screener only.';
  end if;
  select count(*) into n from calls where user_id = uid and created_at > now() - interval '24 hours';
  if n >= 10 then raise exception 'Ten calls a day at most.'; end if;
  insert into calls(user_id, mint, side) values (uid, token, call_side) returning id into new_id;
  return new_id;
exception when unique_violation then
  raise exception 'You already have an open call on this token.';
end $$;

create or replace function public.set_vote(token text, new_vote int) returns int
language plpgsql security definer set search_path = public as $$
declare uid uuid := auth.uid();
begin
  if uid is null then raise exception 'Sign in first.'; end if;
  if not exists (select 1 from profiles where id = uid) then raise exception 'Pick a name first.'; end if;
  if not exists (select 1 from tokens where mint = token) then raise exception 'Unknown token.'; end if;
  if new_vote = 0 then
    delete from votes where user_id = uid and mint = token;
    return 0;
  end if;
  if new_vote not in (-1, 1) then raise exception 'A vote is 1 or -1.'; end if;
  insert into votes(user_id, mint, vote) values (uid, token, new_vote)
    on conflict (user_id, mint) do update set vote = excluded.vote, updated_at = now();
  return new_vote;
end $$;

create or replace function public.toggle_tag(token text, tag_name text) returns boolean
language plpgsql security definer set search_path = public as $$
declare uid uuid := auth.uid();
begin
  if uid is null then raise exception 'Sign in first.'; end if;
  if not exists (select 1 from profiles where id = uid) then raise exception 'Pick a name first.'; end if;
  if not exists (select 1 from tokens where mint = token) then raise exception 'Unknown token.'; end if;
  if exists (select 1 from tags where user_id = uid and mint = token and tag = tag_name) then
    delete from tags where user_id = uid and mint = token and tag = tag_name;
    return false;
  end if;
  insert into tags(user_id, mint, tag) values (uid, token, tag_name);   -- the check constraint rejects unknown tags
  return true;
end $$;

revoke all on function public.set_name(text), public.make_call(text, text), public.set_vote(text, int),
  public.toggle_tag(text, text) from public, anon;
grant execute on function public.set_name(text), public.make_call(text, text), public.set_vote(text, int),
  public.toggle_tag(text, text) to authenticated;
