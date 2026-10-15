"""yuanlei版本迁移拥有的项目主题结构。"""

PROJECT_THEME_SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS project_theme_sources (
        id VARCHAR(36) PRIMARY KEY, kind VARCHAR(16) NOT NULL,
        owner_uid VARCHAR(64) REFERENCES users(uid), project_id VARCHAR(64) REFERENCES projects(id),
        name VARCHAR(160) NOT NULL, description TEXT NOT NULL DEFAULT '',
        status VARCHAR(16) NOT NULL DEFAULT 'active', reason TEXT NOT NULL DEFAULT '',
        candidate_digest VARCHAR(64), candidate_revision INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        copied_from_version_id VARCHAR(36),
        FOREIGN KEY (project_id,owner_uid) REFERENCES projects(id,uid),
        CHECK (kind IN ('builtin','personal','project')),
        CHECK (status IN ('active','disabled','withdrawn')),
        CHECK ((kind='builtin' AND owner_uid IS NULL AND project_id IS NULL)
            OR (kind='personal' AND owner_uid IS NOT NULL AND project_id IS NULL)
            OR (kind='project' AND owner_uid IS NOT NULL AND project_id IS NOT NULL)),
        CHECK (candidate_revision>=0 AND
            ((candidate_revision=0 AND candidate_digest IS NULL) OR
             (candidate_revision>0 AND candidate_digest ~ '^[a-f0-9]{64}$')))
    )""",
    """CREATE TABLE IF NOT EXISTS project_theme_versions (
        id VARCHAR(36) PRIMARY KEY, source_id VARCHAR(36) NOT NULL REFERENCES project_theme_sources(id),
        version VARCHAR(160) NOT NULL, digest VARCHAR(64) NOT NULL,
        size INTEGER NOT NULL CHECK (size>0), format_version INTEGER NOT NULL, component_abi INTEGER NOT NULL,
        candidate_revision INTEGER NOT NULL,
        created_by VARCHAR(64) REFERENCES users(uid), created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(source_id,version), CHECK (digest ~ '^[a-f0-9]{64}$'),
        CHECK (format_version=1 AND component_abi IN (1,2))
    )""",
    """CREATE TABLE IF NOT EXISTS project_theme_bindings (
        project_id VARCHAR(64) PRIMARY KEY REFERENCES projects(id),
        version_id VARCHAR(36) NOT NULL REFERENCES project_theme_versions(id),
        files JSONB NOT NULL, generation INTEGER NOT NULL CHECK(generation>0),
        updated_by VARCHAR(64) NOT NULL REFERENCES users(uid),
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id,updated_by) REFERENCES projects(id,uid),
        CHECK(jsonb_typeof(files)='object')
    )""",
    """CREATE TABLE IF NOT EXISTS project_theme_events (
        id VARCHAR(36) PRIMARY KEY, source_id VARCHAR(36) NOT NULL REFERENCES project_theme_sources(id),
        action VARCHAR(32) NOT NULL, reason TEXT NOT NULL, actor_uid VARCHAR(64) REFERENCES users(uid),
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE OR REPLACE FUNCTION project_theme_version_immutable() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'published theme version is immutable'; END;
        $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS project_theme_version_immutable ON project_theme_versions",
    """CREATE TRIGGER project_theme_version_immutable BEFORE UPDATE OR DELETE ON project_theme_versions
        FOR EACH ROW EXECUTE FUNCTION project_theme_version_immutable()""",
)


PROJECT_THEME_ABI2_STATEMENTS = (
    "ALTER TABLE project_theme_versions DROP CONSTRAINT IF EXISTS project_theme_versions_check",
    "ALTER TABLE project_theme_versions DROP CONSTRAINT IF EXISTS ck_project_theme_versions_abi",
    "ALTER TABLE project_theme_versions ADD CONSTRAINT ck_project_theme_versions_abi "
    "CHECK (format_version=1 AND component_abi IN (1,2))",
)
