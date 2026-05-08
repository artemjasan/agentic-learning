package analyzer

import (
	"database/sql"
	"fmt"

	_ "github.com/lib/pq"
)

// CatalogCache mirrors Postgres's SysCache/CatCache — a per-backend
// in-memory cache of system catalog rows.
//
// In real Postgres, this lives in the backend's private memory (not shared
// memory). Entries are loaded lazily: the first lookup for a given table
// reads from the heap page in shared_buffers, subsequent lookups hit the
// cache directly. Only tables that are actually referenced get cached.
//
// Our implementation queries the database via SQL on cache miss, then
// stores the result — simulating the same lazy "miss → load → hit"
// behavior.
type CatalogCache struct {
	db     *sql.DB
	tables map[string]*PgClassEntry // relname → pg_class entry (cached lazily)
}

// PgClassEntry mirrors a row from pg_class — Postgres's table of all
// relations (tables, indexes, views, sequences, etc.).
type PgClassEntry struct {
	Oid     int
	RelName string
	Columns []*PgAttributeEntry
	colMap  map[string]*PgAttributeEntry
}

// PgAttributeEntry mirrors a row from pg_attribute — Postgres's table of
// all columns across all relations.
type PgAttributeEntry struct {
	AttName  string
	AttNum   int
	TypeName string
}

// OpenCatalog connects to a Postgres database and creates an empty
// catalog cache. Nothing is loaded until the first lookup.
//
// In real Postgres, the catalog cache is initialized empty during
// backend startup. The first query triggers lazy loading.
func OpenCatalog(dsn string) (*CatalogCache, error) {
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		return nil, fmt.Errorf("connect: %w", err)
	}

	return &CatalogCache{
		db:     db,
		tables: make(map[string]*PgClassEntry),
	}, nil
}

// Close releases the database connection.
func (cache *CatalogCache) Close() {
	cache.db.Close()
}

// RelnameGetRelid looks up a table by name. On cache miss, it queries
// pg_class and pg_attribute to load the table definition.
//
// In real Postgres, this calls RelnameGetRelid() which:
//  1. Checks the SysCache hash table for (relname, namespace)
//  2. On miss: reads the pg_class heap page via shared_buffers
//     (using the pg_class_relname_nsp_index for fast lookup)
//  3. Caches the result in SysCache
//  4. On hit: returns the cached entry directly (no locks, no I/O)
//
// Returns nil if the table doesn't exist (like Postgres returning InvalidOid).
func (cache *CatalogCache) RelnameGetRelid(relname string) *PgClassEntry {
	// Cache hit — same as SysCache returning a cached entry
	if entry, exists := cache.tables[relname]; exists {
		fmt.Printf("  %s[catalog cache HIT]%s  %s → oid=%d\n",
			"\033[32m", "\033[0m", relname, entry.Oid)
		return entry
	}

	// Cache miss — load from the catalog tables (in real Postgres: read
	// from shared_buffers, which may trigger a disk read if the page
	// isn't cached there either)
	entry := cache.loadTable(relname)
	if entry == nil {
		fmt.Printf("  %s[catalog cache MISS]%s  %s → not found\n",
			"\033[31m", "\033[0m", relname)
		return nil
	}

	fmt.Printf("  %s[catalog cache MISS]%s  %s → loaded oid=%d (%d columns)\n",
		"\033[33m", "\033[0m", relname, entry.Oid, len(entry.Columns))

	cache.tables[relname] = entry
	return entry
}

// GetColumnByName looks up a column in a table by name.
//
// In real Postgres: get_attnum() searches pg_attribute via SysCache
// with key (attrelid, attname). No I/O if the table was already loaded.
func (cache *CatalogCache) GetColumnByName(table *PgClassEntry, colName string) *PgAttributeEntry {
	return table.colMap[colName]
}

// GetAllColumns returns all columns for a table, ordered by attnum.
func (cache *CatalogCache) GetAllColumns(table *PgClassEntry) []*PgAttributeEntry {
	return table.Columns
}

// DumpCache prints the current cache contents — only what has been
// loaded so far, not the entire database catalog.
func (cache *CatalogCache) DumpCache() {
	fmt.Printf("\n%sCatalog Cache Contents%s\n", "\033[1m", "\033[0m")
	fmt.Printf("%s(only tables that were actually looked up)%s\n\n", "\033[2m", "\033[0m")

	if len(cache.tables) == 0 {
		fmt.Printf("  %s(empty — no lookups performed yet)%s\n\n", "\033[2m", "\033[0m")
		return
	}

	for _, table := range cache.tables {
		fmt.Printf("  %spg_class[%d]%s → %s%s%s\n",
			"\033[2m", table.Oid, "\033[0m",
			"\033[36m", table.RelName, "\033[0m")

		for _, col := range table.Columns {
			fmt.Printf("    %spg_attribute[%d]%s → %s%-15s%s  %s%s%s\n",
				"\033[2m", col.AttNum, "\033[0m",
				"\033[32m", col.AttName, "\033[0m",
				"\033[33m", col.TypeName, "\033[0m")
		}
		fmt.Println()
	}
}

// loadTable queries pg_class and pg_attribute for a single table.
//
// In real Postgres, this would be a SysCache lookup that:
//  1. Searches pg_class via the relname index → gets the OID
//  2. Searches pg_attribute via the attrelid index → gets all columns
//  3. Looks up each column's type via pg_type
// All through shared_buffers, possibly triggering disk reads.
func (cache *CatalogCache) loadTable(relname string) *PgClassEntry {
	// Step 1: look up the table in pg_class
	var oid int
	err := cache.db.QueryRow(`
		SELECT c.oid
		FROM pg_class c
		WHERE c.relname = $1
		  AND c.relkind = 'r'
		  AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
	`, relname).Scan(&oid)
	if err != nil {
		return nil
	}

	entry := &PgClassEntry{
		Oid:     oid,
		RelName: relname,
		colMap:  make(map[string]*PgAttributeEntry),
	}

	// Step 2: load columns from pg_attribute + pg_type
	rows, err := cache.db.Query(`
		SELECT a.attname, a.attnum, t.typname
		FROM pg_attribute a
		JOIN pg_type t ON t.oid = a.atttypid
		WHERE a.attrelid = $1
		  AND a.attnum > 0
		  AND NOT a.attisdropped
		ORDER BY a.attnum
	`, oid)
	if err != nil {
		return entry
	}
	defer rows.Close()

	for rows.Next() {
		var col PgAttributeEntry
		if err := rows.Scan(&col.AttName, &col.AttNum, &col.TypeName); err != nil {
			continue
		}
		entry.Columns = append(entry.Columns, &col)
		entry.colMap[col.AttName] = &col
	}

	return entry
}
