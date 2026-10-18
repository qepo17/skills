# Stack Do/Don't sources

Optional, per stack: read a section only when the repository uses that stack, and skip every other section. Each section's sources feed that stack's Do and Don't subsections in the generated file. Match recommendations to the version the project pins.

## Go

Detected by `go.mod`. Pinned version: the `go` directive.

- Effective Go: https://go.dev/doc/effective_go
- Go Code Review Comments: https://go.dev/wiki/CodeReviewComments
- Google Go Style Guide, best practices: https://google.github.io/styleguide/go/best-practices
- Uber Go Style Guide: https://github.com/uber-go/guide/blob/master/style.md
- 100 Go Mistakes: https://100go.co/
- Working with errors: https://go.dev/blog/go1.13-errors
- Context and structs: https://go.dev/blog/context-and-structs
- Security best practices: https://go.dev/doc/security/best-practices
- Release history, for features at and below the pinned version: https://go.dev/doc/devel/release

## TypeScript

Detected by `tsconfig.json` or a `typescript` dependency. Pinned version: the `typescript` entry in the lockfile.

- Declaration Do's and Don'ts: https://www.typescriptlang.org/docs/handbook/declaration-files/do-s-and-don-ts.html
- Narrowing: https://www.typescriptlang.org/docs/handbook/2/narrowing.html
- TSConfig reference: https://www.typescriptlang.org/tsconfig/
- Choosing module compiler options: https://www.typescriptlang.org/docs/handbook/modules/guides/choosing-compiler-options.html
- Google TypeScript Style Guide: https://google.github.io/styleguide/tsguide.html
- typescript-eslint shared configs: https://typescript-eslint.io/users/configs/
- no-floating-promises: https://typescript-eslint.io/rules/no-floating-promises/
- TypeScript 6.0 defaults and deprecations: https://devblogs.microsoft.com/typescript/announcing-typescript-6-0/
- TypeScript 7.0: https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/

## PostgreSQL

Detected by SQL migrations, a Postgres driver or ORM dialect (`pg`, `postgres`, `pgx`, `psycopg`, `sqlc` with `engine: postgresql`), or a `postgres` image in compose or CI files. Pinned version: the image tag or documented server version, read from files.

- Don't Do This: https://wiki.postgresql.org/wiki/Don%27t_Do_This
- Indexes: https://www.postgresql.org/docs/current/indexes.html
- Using EXPLAIN: https://www.postgresql.org/docs/current/using-explain.html
- Explicit locking: https://www.postgresql.org/docs/current/explicit-locking.html
- Transaction isolation: https://www.postgresql.org/docs/current/transaction-iso.html
- Routine vacuuming: https://www.postgresql.org/docs/current/routine-vacuuming.html
- Use The Index, Luke: https://use-the-index-luke.com/
- Zero-downtime migrations: https://gocardless.com/blog/zero-downtime-postgres-migrations-the-hard-parts/
- Migration lock_timeout and retries: https://postgres.ai/blog/20210923-zero-downtime-postgres-schema-migrations-lock-timeout-and-retries
- strong_migrations checks: https://github.com/ankane/strong_migrations
- Versioning policy: https://www.postgresql.org/support/versioning/
