# Graph Report - .  (2026-08-12)

## Corpus Check
- Corpus is ~4,599 words - fits in a single context window. You may not need a graph.

## Summary
- 126 nodes · 262 edges · 14 communities (13 shown, 1 thin omitted)
- Extraction: 83% EXTRACTED · 17% INFERRED · 0% AMBIGUOUS · INFERRED: 44 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13

## God Nodes (most connected - your core abstractions)
1. `Portal — Proyectos` - 15 edges
2. `Panel admin — Portal` - 14 edges
3. `Grafos Graphify — Admin` - 11 edges
4. `get_admin_id()` - 10 edges
5. `_docker_request()` - 9 edges
6. `_container_states()` - 9 edges
7. `_resolve_service_containers()` - 9 edges
8. `get_system_metrics()` - 8 edges
9. `_connect()` - 7 edges
10. `_stop_container()` - 7 edges

## Surprising Connections (you probably didn't know these)
- `get_system_metrics()` --indirect_call--> `_container_states()`  [INFERRED]
  system_monitor.py → docker_control.py
- `Flask` --conceptually_related_to--> `Grafos Graphify — Admin`  [INFERRED]
  requirements.txt → templates/admin_graphify.html
- `Flask` --conceptually_related_to--> `Admin — Portal (login)`  [INFERRED]
  requirements.txt → templates/admin_login.html
- `Flask` --conceptually_related_to--> `Portal — Proyectos`  [INFERRED]
  requirements.txt → templates/portal.html
- `admin_login()` --calls--> `get_admin_id()`  [EXTRACTED]
  portal-server.py → auth.py

## Import Cycles
- None detected.

## Communities (14 total, 1 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.21
Nodes (18): _container_is_running(), _container_running(), _container_states(), container_to_project_map(), _docker_request(), _DockerSocketConnection, _health_check(), _is_already_stopped_error() (+10 more)

### Community 1 - "Community 1"
Cohesion: 0.31
Nodes (13): logout_admin(), admin_graphify_file(), admin_graphify_index(), admin_graphify_project(), admin_logout(), admin_panel(), _clear_session_cookie(), _graphify_out_dir() (+5 more)

### Community 2 - "Community 2"
Cohesion: 0.16
Nodes (14): /admin/containers/{key}/start, /admin/containers/{key}/stop, Métricas CPU y MEM, Proyectos Docker, htop — proyectos, Datos persistentes instance/, /admin/api/metrics, Monitor del sistema (+6 more)

### Community 3 - "Community 3"
Cohesion: 0.31
Nodes (10): Flask, Sin registro público, Alta solo por admin autenticado, Crear administrador, Nuevo admin — Portal, /admin (Panel), Lista de administradores, /admin/admins/new (+2 more)

### Community 4 - "Community 4"
Cohesion: 0.22
Nodes (10): Waitress, / (Portal), Administración del portal, Admin — Portal (login), Enlace volver al portal, /admin/login, /admin, Portal de proyectos (+2 more)

### Community 5 - "Community 5"
Cohesion: 0.42
Nodes (7): authenticate(), _connect(), create_admin(), _db_path(), init_db(), list_admins(), normalize_email()

### Community 6 - "Community 6"
Cohesion: 0.33
Nodes (9): get_admin(), get_admin_id(), context_processor, admin_create_admin(), admin_metrics_api(), admin_start_container(), admin_stop_container(), inject_admin() (+1 more)

### Community 7 - "Community 7"
Cohesion: 0.42
Nodes (8): _calc_cpu_percent(), _container_stats(), _fetch_container_stats_batch(), _format_bytes(), get_system_metrics(), _host_info(), Métricas de CPU y memoria vía Docker API (estilo htop por proyecto)., Obtiene stats de varios contenedores en paralelo (cada llamada a Docker tarda…

### Community 8 - "Community 8"
Cohesion: 0.29
Nodes (8): /admin, Grafos de código, Grafos Graphify — Admin, /static/css/portal.css, Visualización privada de grafos, /admin/graphify, /static/css/portal.css, /admin/graphify

### Community 9 - "Community 9"
Cohesion: 0.29
Nodes (8): graphify-out, graphify update, graphs (proyectos con grafo), graphify_graphs, graphify-out/graph.html, Grafos Graphify (panel), projects (proyectos disponibles), projects.json

### Community 10 - "Community 10"
Cohesion: 0.40
Nodes (5): Campo email (login), Formulario inicio de sesión admin, Campo contraseña (login), Formulario alta administrador, Contraseña mín. 8 caracteres

### Community 11 - "Community 11"
Cohesion: 0.50
Nodes (4): /admin/logout, /admin/logout, /admin/logout, /admin/logout

### Community 12 - "Community 12"
Cohesion: 0.67
Nodes (3): current_admin, current_admin, current_admin (nav condicional)

## Knowledge Gaps
- **9 isolated node(s):** `graphify update`, `Administración del portal`, `Campo contraseña (login)`, `Contraseña mín. 8 caracteres`, `/admin/containers/{key}/stop` (+4 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Panel admin — Portal` connect `Community 3` to `Community 2`, `Community 4`, `Community 8`, `Community 9`, `Community 10`, `Community 11`, `Community 12`?**
  _High betweenness centrality (0.089) - this node is a cross-community bridge._
- **Why does `Portal — Proyectos` connect `Community 4` to `Community 2`, `Community 3`, `Community 8`, `Community 9`, `Community 11`, `Community 12`?**
  _High betweenness centrality (0.068) - this node is a cross-community bridge._
- **Why does `Flask` connect `Community 3` to `Community 8`, `Community 4`?**
  _High betweenness centrality (0.043) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `Portal — Proyectos` (e.g. with `Flask` and `/ (Portal)`) actually correct?**
  _`Portal — Proyectos` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `Panel admin — Portal` (e.g. with `Flask` and `/admin`) actually correct?**
  _`Panel admin — Portal` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `Grafos Graphify — Admin` (e.g. with `Flask` and `/admin/graphify`) actually correct?**
  _`Grafos Graphify — Admin` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `graphify update`, `Administración del portal`, `Campo contraseña (login)` to the rest of the system?**
  _9 weakly-connected nodes found - possible documentation gaps or missing edges._