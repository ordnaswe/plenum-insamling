-- Kör i Supabase SQL Editor (engång): start/slutdatum på uppdrag + uppdaterad vy
alter table uppdrag add column if not exists start_datum date;
alter table uppdrag add column if not exists slut_datum date;
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
