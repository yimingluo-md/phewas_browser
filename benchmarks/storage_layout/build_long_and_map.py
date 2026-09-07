"""Chunked (per gene, resumable) conversion of the wide assoc table into long and MAP layouts."""
import duckdb, time, sys, os
SRC = os.path.expanduser("~/mnt/phewas_browser/data/phewas.duckdb")
DST = os.path.expanduser("~/bench/bench.duckdb")
BUDGET = float(sys.argv[1]) if len(sys.argv) > 1 else 140
t_start = time.time()
con = duckdb.connect(DST)
con.execute("SET memory_limit='1000MB'"); con.execute("SET threads=2")
con.execute(f"SET temp_directory='{os.path.expanduser('~/bench/tmp')}'")
con.execute(f"ATTACH '{SRC}' AS src (READ_ONLY)")
con.execute("""CREATE TABLE IF NOT EXISTS assoc_long (
  variant_id VARCHAR, gene VARCHAR, trait VARCHAR, cohort VARCHAR,
  "or" DOUBLE, p DOUBLE, cases INTEGER, case_carriers INTEGER, controls INTEGER, ctrl_carriers INTEGER)""")
con.execute("""CREATE TABLE IF NOT EXISTS assoc_map (
  variant_id VARCHAR, gene VARCHAR, trait VARCHAR, source VARCHAR,
  stats MAP(VARCHAR, STRUCT("or" DOUBLE, p DOUBLE, cases INTEGER, case_carriers INTEGER, controls INTEGER, ctrl_carriers INTEGER)))""")
con.execute("CREATE TABLE IF NOT EXISTS done_genes (gene VARCHAR)")
genes = [r[0] for r in con.sql("SELECT gene FROM src.gene_summary WHERE gene NOT IN (SELECT gene FROM done_genes) ORDER BY gene").fetchall()]
print(f"{len(genes)} genes remaining")
for g in genes:
    if time.time() - t_start > BUDGET:
        print("budget reached"); break
    t = time.time()
    con.execute("DELETE FROM assoc_long WHERE gene = ?", [g]); con.execute("DELETE FROM assoc_map WHERE gene = ?", [g])
    names = [r[0] for r in con.execute("SELECT DISTINCT name FROM src.assoc WHERE gene = ? ORDER BY name", [g]).fetchall()]
    CH = 150  # variants per chunk (~250k wide rows)
    for i in range(0, len(names), CH):
        lo, hi = names[i], names[min(i + CH, len(names)) - 1]
        con.execute("BEGIN")
        con.execute("""INSERT INTO assoc_long
        SELECT name, gene, trait, cohort, "or", p, cases, case_carriers, controls, ctrl_carriers FROM (
          SELECT name, gene, trait, 'META' AS cohort, or_meta AS "or", p_meta AS p, cases_meta AS cases, casecarr_meta AS case_carriers, controls_meta AS controls, ctrlcarr_meta AS ctrl_carriers FROM src.assoc WHERE gene = ? AND name BETWEEN ? AND ?
          UNION ALL
          SELECT name, gene, trait, 'AoU', or_aou, p_aou, cases_aou, casecarr_aou, controls_aou, ctrlcarr_aou FROM src.assoc WHERE gene = ? AND name BETWEEN ? AND ? AND (or_aou IS NOT NULL OR p_aou IS NOT NULL OR cases_aou IS NOT NULL)
          UNION ALL
          SELECT name, gene, trait, 'UKBB', or_ukbb, p_ukbb, cases_ukbb, casecarr_ukbb, controls_ukbb, ctrlcarr_ukbb FROM src.assoc WHERE gene = ? AND name BETWEEN ? AND ? AND (or_ukbb IS NOT NULL OR p_ukbb IS NOT NULL OR cases_ukbb IS NOT NULL)
        ) ORDER BY gene, name, trait, cohort""", [g, lo, hi] * 3)
        con.execute("""INSERT INTO assoc_map
        SELECT name, gene, trait, source,
          map_from_entries(list_filter([
            struct_pack(key := 'META', value := struct_pack("or" := or_meta, p := p_meta, cases := cases_meta, case_carriers := casecarr_meta, controls := controls_meta, ctrl_carriers := ctrlcarr_meta)),
            struct_pack(key := 'AoU',  value := struct_pack("or" := or_aou,  p := p_aou,  cases := cases_aou,  case_carriers := casecarr_aou,  controls := controls_aou,  ctrl_carriers := ctrlcarr_aou)),
            struct_pack(key := 'UKBB', value := struct_pack("or" := or_ukbb, p := p_ukbb, cases := cases_ukbb, case_carriers := casecarr_ukbb, controls := controls_ukbb, ctrl_carriers := ctrlcarr_ukbb))
          ], e -> e.value.p IS NOT NULL OR e.value.cases IS NOT NULL)) AS stats
        FROM src.assoc WHERE gene = ? AND name BETWEEN ? AND ? ORDER BY gene, name, trait""", [g, lo, hi])
        con.execute("COMMIT")
    con.execute("INSERT INTO done_genes VALUES (?)", [g])
    n = con.sql("SELECT count(*) FROM src.assoc WHERE gene = ?".replace("?", f"'{g}'")).fetchone()[0]
    print(f"  {g}: {n:,} wide rows in {time.time()-t:.1f}s")
print("remaining:", con.sql("SELECT count(*) FROM src.gene_summary WHERE gene NOT IN (SELECT gene FROM done_genes)").fetchone()[0])
con.close()
