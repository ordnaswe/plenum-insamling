-- Plenum: schema för förtroendevalda i kommuner och regioner
-- Kör i Supabase SQL Editor. Idempotent (if not exists).

create extension if not exists pgcrypto;

-- 1. Organisationer (290 kommuner + 21 regioner)
create table if not exists organisationer (
  org_slug      text primary key,            -- "haninge", "region-skane"
  namn          text not null,
  kommunkod     text,                        -- 4 siffror (kommun) / 2 siffror länskod (region)
  typ           text not null check (typ in ('kommun','region')),
  system        text,                        -- troman | egen | ingen | ...
  adapter       text,
  base_url      text,
  aktiv         boolean not null default true,
  kommentar     text,
  uppdaterad    timestamptz not null default now()
);

-- 2. Organ: nämnd, styrelse, bolag, utskott ...
create table if not exists organ (
  id            uuid primary key default gen_random_uuid(),
  org_slug      text not null references organisationer(org_slug),
  organ_norm    text not null,               -- nyckelform (gemener)
  namn          text not null,               -- som källan skriver det
  organ_typ     text not null default 'ovrigt',
  extern_id     text,
  kalla_url     text,
  forst_sedd    date not null default current_date,
  senast_sedd   date not null default current_date,
  aktiv         boolean not null default true,
  unique (org_slug, organ_norm)
);

-- 3. Personer: en rad per person och organisation
--    (samma människa i kommun + region = två rader; koppling görs senare via namn+parti om man vill)
create table if not exists personer (
  person_nyckel text primary key,            -- sha1(org|förnamn|efternamn)
  org_slug      text not null references organisationer(org_slug),
  fornamn       text not null default '',
  efternamn     text not null,
  namn_raw      text not null,
  namn_osakert  boolean not null default false,
  parti         text not null default '',    -- S, M, SD ... eller lokalt partinamn
  parti_raw     text not null default '',
  epost         text,
  epost_kalla_url text,
  epost_sedd    date,
  forst_sedd    date not null default current_date,
  senast_sedd   date not null default current_date,
  aktiv         boolean not null default true
);
create index if not exists personer_org_idx on personer(org_slug);
create index if not exists personer_namn_idx on personer(efternamn, fornamn);
create index if not exists personer_parti_idx on personer(parti);

-- 4. Uppdrag: person x organ x roll. Historik via forst_sedd/senast_sedd/avslutad.
create table if not exists uppdrag (
  uppdrag_nyckel text primary key,           -- sha1(org|organ_norm|namn|roll)
  person_nyckel text not null references personer(person_nyckel),
  organ_id      uuid not null references organ(id),
  org_slug      text not null references organisationer(org_slug),
  roll          text not null default 'ovrigt',
  roll_raw      text not null default '',
  roll_rang     int  not null default 99,
  kalla_url     text,
  mandatperiod  text,                        -- '2022-2026' för importerad historik
  forst_sedd    date not null default current_date,
  senast_sedd   date not null default current_date,
  start_datum   date,                        -- från källan om den anger det (Troman personsida)
  slut_datum    date,
  avslutad      date,                        -- sätts när uppdraget försvinner ur källan
  aktiv         boolean not null default true
);
create index if not exists uppdrag_person_idx on uppdrag(person_nyckel);
create index if not exists uppdrag_organ_idx on uppdrag(organ_id);
create index if not exists uppdrag_aktiv_idx on uppdrag(org_slug, aktiv);

-- 5. Körningar: en rad per organisation och dag. Grund för kvalitetsövervakning.
create table if not exists korningar (
  id            bigint generated always as identity primary key,
  org_slug      text not null references organisationer(org_slug),
  startad       timestamptz not null default now(),
  avslutad      timestamptz,
  status        text not null default 'pagar',   -- ok | tom | blockerad | fel | ingen_kalla | skippad_sakring
  antal_uppdrag int,
  antal_nya     int,
  antal_avslutade int,
  antal_hamtningar int,
  felmeddelande text,
  ravdata_path  text                              -- sökväg i Storage-bucket 'ravdata'
);
create index if not exists korningar_org_idx on korningar(org_slug, startad desc);

-- 6. Logg över förändringar (vad som kom till / försvann), för "bevakning"-funktionen
create table if not exists forandringar (
  id            bigint generated always as identity primary key,
  tid           timestamptz not null default now(),
  org_slug      text not null,
  typ           text not null,              -- nytt_uppdrag | avslutat_uppdrag | ny_epost | ny_person
  uppdrag_nyckel text,
  person_nyckel text,
  detaljer      jsonb
);
create index if not exists forandringar_tid_idx on forandringar(tid desc);

-- Vy för sajten/API: allt aktivt, läsbart
create or replace view v_aktiva_uppdrag as
select
  u.uppdrag_nyckel, o.namn as organisation, o.typ as org_typ, o.kommunkod,
  p.fornamn, p.efternamn, p.parti, p.epost,
  g.namn as organ, g.organ_typ,
  u.roll, u.roll_raw, u.roll_rang,
  u.start_datum, u.slut_datum, u.mandatperiod,
  u.forst_sedd, u.senast_sedd, u.kalla_url
from uppdrag u
join personer p on p.person_nyckel = u.person_nyckel
join organ g on g.id = u.organ_id
join organisationer o on o.org_slug = u.org_slug
where u.aktiv;

-- Täckning: senaste lyckade körning per organisation
create or replace view v_tackning as
select o.org_slug, o.namn, o.typ, o.system, o.adapter,
       (select max(k.avslutad) from korningar k where k.org_slug=o.org_slug and k.status='ok') as senast_ok,
       (select k.status from korningar k where k.org_slug=o.org_slug order by k.startad desc limit 1) as senaste_status,
       (select count(*) from uppdrag u where u.org_slug=o.org_slug and u.aktiv) as aktiva_uppdrag
from organisationer o;

-- RLS: tjänstenyckeln (GitHub Actions) går förbi RLS. Anon får bara läsa vyerna.
alter table organisationer enable row level security;
alter table organ enable row level security;
alter table personer enable row level security;
alter table uppdrag enable row level security;
alter table korningar enable row level security;
alter table forandringar enable row level security;
drop policy if exists "las_org" on organisationer;
create policy "las_org" on organisationer for select using (true);
drop policy if exists "las_organ" on organ;
create policy "las_organ" on organ for select using (true);
drop policy if exists "las_personer" on personer;
create policy "las_personer" on personer for select using (true);
drop policy if exists "las_uppdrag" on uppdrag;
create policy "las_uppdrag" on uppdrag for select using (true);
-- korningar/forandringar: ingen anon-läsning (ingen policy = ingen åtkomst)

-- Storage-bucket för råa JSONL-snapshots (skapas via Dashboard eller:)
-- insert into storage.buckets (id, name, public) values ('ravdata','ravdata', false) on conflict do nothing;
