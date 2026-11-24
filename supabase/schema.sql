-- AIR BURGUNDY : base Supabase.
-- Les tables et les fonctions internes vivent dans le schéma privé « va », jamais exposé par l'API Supabase.
-- Seules les fonctions api_* (lecture, publiques) et acars_* (écriture, protégées par la clé ACARS)
-- sont accessibles, via /rest/v1/rpc/<nom>.
-- Le script peut être relancé sans risque : il est idempotent.

create schema if not exists va;
revoke all on schema va from public, anon, authenticated;

-- ------------------------------------------------------------------ tables
create table if not exists va.aircraft (
  reg text primary key, name text, type text, engines text, livery text, image text,
  location text, location_airport jsonb, sort int default 0);

create table if not exists va.flights (
  id bigserial primary key, flight_no text, reg text references va.aircraft(reg), pilot text,
  dep text, arr text, planned_arr text, dep_airport jsonb, arr_airport jsonb,
  status text, phase text,
  started double precision, block_off double precision, takeoff double precision, landing double precision,
  block_on double precision, ended double precision,
  distance_nm double precision default 0, fuel_start double precision, fuel_end double precision,
  landing_fpm double precision, landing_g double precision, max_alt double precision default 0,
  last_update double precision, sim text, route jsonb);
create index if not exists flights_status on va.flights(status, last_update);
create index if not exists flights_reg on va.flights(reg, status);

create table if not exists va.positions (
  id bigserial primary key, flight_id bigint references va.flights(id) on delete cascade,
  t double precision, lat double precision, lon double precision, alt double precision,
  gs double precision, hdg double precision, vs double precision, ias double precision, phase text);
create index if not exists positions_flight_t on va.positions(flight_id, t);

create table if not exists va.acars_keys (key text primary key, label text, created_at timestamptz default now());

alter table va.aircraft enable row level security;
alter table va.flights enable row level security;
alter table va.positions enable row level security;
alter table va.acars_keys enable row level security;

-- ------------------------------------------------------------------ flotte
insert into va.aircraft(reg, name, type, engines, livery, image, location, sort) values
  ('F-DIMI', 'Ville de Dijon',    'A321neo XLR', 'PW1130G-JM', 'Classique',         'img/profile-F-DIMI.webp', 'LFSD', 1),
  ('F-NINO', 'Ville de Montceau', 'A321neo XLR', 'PW1130G-JM', 'Classique',         'img/profile-F-NINO.webp', 'LFSD', 2),
  ('F-JERO', 'Ville d’Autun',     'A321neo XLR', 'PW1130G-JM', 'Édition Mosaïque',  'img/profile-F-JERO.webp', 'LFSD', 3),
  ('F-PINO', 'Ville de Beaune',   'A321neo XLR', 'PW1130G-JM', 'Classique',         'img/profile-F-PINO.webp', 'LFSD', 4),
  ('F-LAUR', 'Ville de Mâcon',    'A319',        'CFM56-5B',   'Vendanges',         'img/profile-F-LAUR.webp', 'LFSD', 5)
on conflict (reg) do update set name = excluded.name, type = excluded.type, engines = excluded.engines,
  livery = excluded.livery, image = excluded.image, sort = excluded.sort;
update va.aircraft set location_airport = '{"icao":"LFSD","name":"Dijon Longvic","lat":47.26582,"lon":5.09498}'
  where location = 'LFSD' and location_airport is null;

-- ------------------------------------------------------------------ helpers (privés)
create or replace function va.now() returns double precision language sql stable as
$$ select extract(epoch from clock_timestamp())::double precision $$;

create or replace function va.nm(lat1 float8, lon1 float8, lat2 float8, lon2 float8) returns float8 language sql immutable as
$$ select 3440.065 * 2 * asin(least(1, sqrt(power(sin(radians(lat2 - lat1) / 2), 2)
        + cos(radians(lat1)) * cos(radians(lat2)) * power(sin(radians(lon2 - lon1) / 2), 2)))) $$;

-- les clés ACARS ne sont jamais stockées en clair : va.acars_keys.key contient leur SHA-256 (hex)
create or replace function va.check_key(k text) returns void language plpgsql stable as $$
begin
  if k is null or not exists (select 1 from va.acars_keys where key = encode(sha256(convert_to(k, 'UTF8')), 'hex')) then
    raise exception 'cle ACARS invalide' using errcode = '28000';
  end if;
end $$;

create or replace function va.expire() returns void language sql as
$$ update va.flights set status = 'perdu', ended = last_update
   where status = 'actif' and last_update < va.now() - 6 * 3600 $$;

create or replace function va.flight_json(f va.flights, with_pos boolean default true) returns jsonb language plpgsql stable as $$
declare j jsonb; t0 float8; t1 float8; p jsonb;
begin
  j := to_jsonb(f);
  if f.arr_airport is null and f.route is not null and f.route ? 'destination' then
    j := j || jsonb_build_object('arr_airport', f.route -> 'destination');
  elsif f.arr_airport is null and coalesce(f.arr, f.planned_arr) is not null then
    j := j || jsonb_build_object('arr_airport', jsonb_build_object('icao', coalesce(f.arr, f.planned_arr)));
  end if;
  if f.dep_airport is null and f.dep is not null then
    j := j || jsonb_build_object('dep_airport', jsonb_build_object('icao', f.dep));
  end if;
  t0 := coalesce(f.block_off, f.started); t1 := coalesce(f.block_on, f.ended, f.last_update);
  j := j || jsonb_build_object(
    'block_min', case when t0 is not null and t1 is not null then round((t1 - t0) / 60) end,
    'air_min',   case when f.takeoff is not null then round((coalesce(f.landing, f.last_update) - f.takeoff) / 60) end,
    'fuel_used', case when f.fuel_start is not null and f.fuel_end is not null then round(f.fuel_start - f.fuel_end) end);
  if with_pos then
    select to_jsonb(x) into p from (
      select flight_id, t, lat, lon, alt, gs, hdg, vs, ias, phase from va.positions
      where flight_id = f.id order by t desc limit 1) x;
    j := j || jsonb_build_object('position', p);
  end if;
  return j;
end $$;

-- ------------------------------------------------------------------ API publique (lecture)
create or replace function public.api_live() returns jsonb language plpgsql security definer set search_path = va, public as $$
declare res jsonb;
begin
  perform va.expire();
  select coalesce(jsonb_agg(va.flight_json(f) || jsonb_build_object('track',
           (select coalesce(jsonb_agg(jsonb_build_array(p.lat, p.lon, p.alt) order by p.t), '[]'::jsonb)
              from va.positions p where p.flight_id = f.id)) order by f.started), '[]'::jsonb)
    into res
    from va.flights f where f.status = 'actif' and f.last_update > va.now() - 180;
  return jsonb_build_object('server_time', va.now(), 'flights', res);
end $$;

create or replace function public.api_fleet() returns jsonb language sql security definer set search_path = va, public as $$
  select coalesce(jsonb_agg(to_jsonb(a) || jsonb_build_object(
           'flights', s.n, 'hours', round((s.air / 3600)::numeric, 1), 'distance_nm', round(s.dist::numeric),
           'live', (select va.flight_json(f) from va.flights f
                     where f.reg = a.reg and f.status = 'actif' and f.last_update > va.now() - 180
                     order by f.started desc limit 1),
           'location_airport', coalesce(a.location_airport, jsonb_build_object('icao', a.location)))
         order by a.sort), '[]'::jsonb)
  from va.aircraft a
  cross join lateral (select count(*) n, coalesce(sum(landing - takeoff), 0) air, coalesce(sum(distance_nm), 0) dist
                        from va.flights where reg = a.reg and status = 'termine') s
$$;

create or replace function public.api_flights(p_limit int default 50, p_reg text default null) returns jsonb
language sql security definer set search_path = va, public as $$
  select coalesce(jsonb_agg(va.flight_json(f, false) order by f.started desc), '[]'::jsonb)
  from va.flights f
  where f.id in (select id from va.flights
                  where status <> 'actif' and (p_reg is null or reg = upper(p_reg))
                  order by started desc limit least(greatest(coalesce(p_limit, 50), 1), 500))
$$;

create or replace function public.api_flight(p_id bigint) returns jsonb language sql security definer set search_path = va, public as $$
  select va.flight_json(f) || jsonb_build_object('track',
           (select coalesce(jsonb_agg(jsonb_build_object('t', t, 'lat', lat, 'lon', lon, 'alt', alt, 'gs', gs,
                     'hdg', hdg, 'vs', vs, 'ias', ias, 'phase', phase) order by t), '[]'::jsonb)
              from va.positions where flight_id = f.id))
  from va.flights f where f.id = p_id
$$;

create or replace function public.api_stats() returns jsonb language sql security definer set search_path = va, public as $$
  select jsonb_build_object(
    'flights', count(*), 'hours', round((coalesce(sum(landing - takeoff), 0) / 3600)::numeric, 1),
    'distance_nm', round(coalesce(sum(distance_nm), 0)::numeric), 'fuel_kg', round(coalesce(sum(fuel_start - fuel_end), 0)::numeric),
    'destinations', count(distinct arr), 'avg_landing_fpm', round(avg(landing_fpm)::numeric),
    'best_landing', (select jsonb_build_object('id', id, 'flight_no', flight_no, 'reg', reg, 'arr', arr, 'landing_fpm', landing_fpm)
                       from va.flights where status = 'termine' and landing_fpm is not null order by landing_fpm desc limit 1),
    'live', (select count(*) from va.flights where status = 'actif' and last_update > va.now() - 180))
  from va.flights where status = 'termine'
$$;

-- ------------------------------------------------------------------ ACARS (écriture, clé obligatoire)
create or replace function public.acars_start(p_key text, p jsonb) returns jsonb language plpgsql security definer set search_path = va, public as $$
declare v_reg text := upper(coalesce(p ->> 'reg', '')); rt jsonb := nullif(p -> 'route', 'null'::jsonb);
        v_arr text; v_fno text; v_id bigint; n float8 := va.now();
begin
  perform va.check_key(p_key);
  if not exists (select 1 from va.aircraft where reg = v_reg) then
    raise exception '% n''est pas un avion AIR BURGUNDY', v_reg;
  end if;
  update va.flights set status = 'interrompu', ended = last_update where reg = v_reg and status = 'actif';
  v_arr := upper(nullif(coalesce(p ->> 'arr', rt -> 'destination' ->> 'icao'), ''));
  v_fno := coalesce(nullif(p ->> 'flight_no', ''), rt ->> 'flight_no', 'BRG' || (101 + (select count(*) from va.flights)));
  insert into va.flights(flight_no, reg, pilot, dep, planned_arr, dep_airport, status, phase, started, last_update, fuel_start, sim, route)
  values (v_fno, v_reg, p ->> 'pilot', upper(nullif(p ->> 'dep', '')), v_arr, nullif(p -> 'dep_airport', 'null'::jsonb),
          'actif', coalesce(p ->> 'phase', 'Embarquement'), n, n, (p ->> 'fuel')::float8, coalesce(p ->> 'sim', 'X-Plane'), rt)
  returning id into v_id;
  return jsonb_build_object('flight_id', v_id, 'flight_no', v_fno);
end $$;

create or replace function public.acars_pos(p_key text, p jsonb) returns jsonb language plpgsql security definer set search_path = va, public as $$
declare f va.flights; pt jsonb; la float8; lo float8; dist float8; maxalt float8; ph text; cnt int := 0;
        ev jsonb := coalesce(p -> 'events', '{}'::jsonb); n float8 := va.now();
begin
  perform va.check_key(p_key);
  select * into f from va.flights where id = (p ->> 'flight_id')::bigint;
  if not found then raise exception 'vol inconnu'; end if;
  select lat, lon into la, lo from va.positions where flight_id = f.id order by t desc limit 1;
  dist := coalesce(f.distance_nm, 0); maxalt := coalesce(f.max_alt, 0); ph := f.phase;
  for pt in select * from jsonb_array_elements(coalesce(p -> 'positions', '[]'::jsonb)) loop
    if la is not null and coalesce((pt ->> 'gs')::float8, 0) > 30 then
      dist := dist + va.nm(la, lo, (pt ->> 'lat')::float8, (pt ->> 'lon')::float8);
    end if;
    la := (pt ->> 'lat')::float8; lo := (pt ->> 'lon')::float8;
    maxalt := greatest(maxalt, coalesce((pt ->> 'alt')::float8, 0));
    insert into va.positions(flight_id, t, lat, lon, alt, gs, hdg, vs, ias, phase)
    values (f.id, coalesce((pt ->> 't')::float8, n), la, lo, (pt ->> 'alt')::float8, (pt ->> 'gs')::float8,
            (pt ->> 'hdg')::float8, (pt ->> 'vs')::float8, (pt ->> 'ias')::float8, pt ->> 'phase');
    ph := coalesce(pt ->> 'phase', ph); cnt := cnt + 1;
  end loop;
  update va.flights set distance_nm = dist, max_alt = maxalt, last_update = n, phase = ph,
    block_off   = coalesce(block_off,   (ev ->> 'block_off')::float8),
    takeoff     = coalesce(takeoff,     (ev ->> 'takeoff')::float8),
    landing     = coalesce(landing,     (ev ->> 'landing')::float8),
    landing_fpm = coalesce(landing_fpm, (ev ->> 'landing_fpm')::float8),
    landing_g   = coalesce(landing_g,   (ev ->> 'landing_g')::float8),
    dep         = coalesce(dep, upper(nullif(ev ->> 'dep', ''))),
    dep_airport = coalesce(dep_airport, nullif(ev -> 'dep_airport', 'null'::jsonb))
  where id = f.id;
  return jsonb_build_object('ok', true, 'stored', cnt);
end $$;

create or replace function public.acars_route(p_key text, p jsonb) returns jsonb language plpgsql security definer set search_path = va, public as $$
declare rt jsonb := coalesce(p -> 'route', '{}'::jsonb);
begin
  perform va.check_key(p_key);
  update va.flights set route = rt,
    planned_arr = coalesce(rt -> 'destination' ->> 'icao', planned_arr),
    flight_no   = coalesce(rt ->> 'flight_no', flight_no)
  where id = (p ->> 'flight_id')::bigint;
  if not found then raise exception 'vol inconnu'; end if;
  return jsonb_build_object('ok', true, 'fixes', jsonb_array_length(coalesce(rt -> 'fixes', '[]'::jsonb)));
end $$;

create or replace function public.acars_end(p_key text, p jsonb) returns jsonb language plpgsql security definer set search_path = va, public as $$
declare f va.flights; v_status text := coalesce(p ->> 'status', 'termine'); v_arr text; v_apt jsonb; n float8 := va.now();
begin
  perform va.check_key(p_key);
  select * into f from va.flights where id = (p ->> 'flight_id')::bigint;
  if not found then raise exception 'vol inconnu'; end if;
  v_arr := upper(nullif(coalesce(p ->> 'arr', f.planned_arr), ''));
  v_apt := nullif(p -> 'arr_airport', 'null'::jsonb);
  update va.flights set status = v_status,
    phase = case when v_status = 'termine' then 'Arrivé' else initcap(v_status) end,
    arr = v_arr, arr_airport = coalesce(v_apt, arr_airport),
    block_on = coalesce((p ->> 'block_on')::float8, n), ended = n, fuel_end = (p ->> 'fuel')::float8, last_update = n,
    landing     = coalesce(landing,     (p ->> 'landing')::float8),
    landing_fpm = coalesce(landing_fpm, (p ->> 'landing_fpm')::float8),
    landing_g   = coalesce(landing_g,   (p ->> 'landing_g')::float8)
  where id = f.id;
  if v_status = 'termine' and v_arr is not null then
    update va.aircraft set location = v_arr, location_airport = coalesce(v_apt, jsonb_build_object('icao', v_arr)) where reg = f.reg;
  end if;
  return jsonb_build_object('ok', true);
end $$;

alter function va.now() set search_path = va, pg_catalog;
alter function va.nm(float8, float8, float8, float8) set search_path = va, pg_catalog;
alter function va.check_key(text) set search_path = va, pg_catalog;
alter function va.expire() set search_path = va, pg_catalog;
alter function va.flight_json(va.flights, boolean) set search_path = va, pg_catalog;

-- ------------------------------------------------------------------ droits
revoke all on all tables in schema va from public, anon, authenticated;
revoke all on all functions in schema va from public, anon, authenticated;
do $$ declare fn text; begin
  foreach fn in array array['api_live()', 'api_fleet()', 'api_flights(int, text)', 'api_flight(bigint)', 'api_stats()',
                            'acars_start(text, jsonb)', 'acars_pos(text, jsonb)', 'acars_route(text, jsonb)', 'acars_end(text, jsonb)'] loop
    execute format('revoke all on function public.%s from public', fn);
    execute format('grant execute on function public.%s to anon, authenticated', fn);
  end loop;
end $$;
