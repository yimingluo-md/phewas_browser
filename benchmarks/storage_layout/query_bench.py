import duckdb, time, os, statistics as st
W = duckdb.connect(os.path.expanduser("~/mnt/phewas_browser/data/phewas.duckdb"), read_only=True)
B = duckdb.connect(os.path.expanduser("~/bench/bench.duckdb"), read_only=True)
for c in (W, B): c.execute("SET memory_limit='1000MB'"); c.execute("SET threads=4")
vs = W.sql("SELECT name, gene FROM variant_index ORDER BY hash(name) LIMIT 5").fetchall() + [("12:49038733:C:A", "KMT2D")]
def timeit(con, sql, params=(), reps=5):
    ts = []
    for _ in range(reps):
        t = time.perf_counter(); n = len(con.execute(sql, params).fetchall()); ts.append(time.perf_counter() - t)
    return f"first {ts[0]*1000:6.1f} ms  median {st.median(ts[1:])*1000:6.1f} ms  rows {n}"
print("== variant page (6 variants, each 5 reps) ==")
for name, gene in vs:
    print(f"-- {name} {gene}")
    print("  wide ", timeit(W, "SELECT * FROM assoc WHERE name=? AND gene=?", [name, gene]))
    print("  long ", timeit(B, "SELECT * FROM assoc_long WHERE variant_id=? AND gene=?", [name, gene]))
    print("  long pivoted", timeit(B, """SELECT trait, map_from_entries(list(struct_pack(key := cohort, value := struct_pack("or" := "or", p := p, cases := cases, case_carriers := case_carriers, controls := controls, ctrl_carriers := ctrl_carriers)))) FROM assoc_long WHERE variant_id=? AND gene=? GROUP BY trait""", [name, gene]))
    print("  map  ", timeit(B, "SELECT * FROM assoc_map WHERE variant_id=? AND gene=?", [name, gene]))
print("== gene index rebuild (KMT2D, largest gene: 9.6M wide rows) ==")
print("  wide ", timeit(W, "SELECT name, count(*), min(p_meta), arg_min(trait, p_meta) FROM assoc WHERE gene='KMT2D' GROUP BY name", reps=3))
print("  long ", timeit(B, "SELECT variant_id, count(*), min(p), arg_min(trait, p) FROM assoc_long WHERE gene='KMT2D' AND cohort='META' GROUP BY variant_id", reps=3))
print("  map  ", timeit(B, "SELECT variant_id, count(*), min(stats['META'].p), arg_min(trait, stats['META'].p) FROM assoc_map WHERE gene='KMT2D' GROUP BY variant_id", reps=3))
print("== trait slice: all KMT2D variants for one phecode (future feature) ==")
print("  wide ", timeit(W, "SELECT name, or_meta, p_meta FROM assoc WHERE gene='KMT2D' AND trait='250.2'", reps=3))
print("  long ", timeit(B, "SELECT variant_id, \"or\", p FROM assoc_long WHERE gene='KMT2D' AND trait='250.2' AND cohort='META'", reps=3))
print("  map  ", timeit(B, "SELECT variant_id, stats['META'].\"or\", stats['META'].p FROM assoc_map WHERE gene='KMT2D' AND trait='250.2'", reps=3))
print("== dataset-wide: top 20 hits (full scan) ==")
print("  wide ", timeit(W, "SELECT name, gene, trait, p_meta FROM assoc ORDER BY p_meta LIMIT 20", reps=2))
print("  long ", timeit(B, "SELECT variant_id, gene, trait, p FROM assoc_long WHERE cohort='META' ORDER BY p LIMIT 20", reps=2))
print("  map  ", timeit(B, "SELECT variant_id, gene, trait, stats['META'].p AS p FROM assoc_map ORDER BY p LIMIT 20", reps=2))
print("== are cases/controls constant per (trait, cohort)? ==")
print(W.sql("SELECT count(*) AS n_traits, sum(CASE WHEN n_distinct_cases > 1 THEN 1 ELSE 0 END) AS traits_with_varying_cases FROM (SELECT trait, count(DISTINCT cases_meta) n_distinct_cases FROM assoc GROUP BY trait)").fetchall())
print(W.sql("SELECT count(*) AS n_traits, sum(CASE WHEN n > 1 THEN 1 ELSE 0 END) FROM (SELECT trait, count(DISTINCT (cases_aou, controls_aou, cases_ukbb, controls_ukbb)) n FROM assoc GROUP BY trait)").fetchall())
