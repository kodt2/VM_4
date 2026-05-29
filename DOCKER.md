# Docker deployment

This project is packaged as a single container image that contains both parts of the application:

1. the C++ JSON CLI solver (`poisson_sor`), built in a dedicated CMake stage;
2. the Python FastAPI web server, static frontend assets, and Plotly figure generation code.

## Files

- `Dockerfile` — multi-stage image build. The first stage compiles `src/main.cpp`; the runtime stage installs only web Python dependencies and copies the compiled solver to `/app/build/poisson_sor`.
- `docker-compose.yml` — local orchestration for the web service.
- `.dockerignore` — keeps local build products, virtual environments, caches, and Git metadata out of the build context.
- `requirements-web.txt` — minimal Python dependencies for the containerized web service. The original `requirements.txt` still includes desktop GUI dependencies for local PyQt usage.

## Quick start

```bash
docker compose up --build
```

Open <http://localhost:8000>.

To use another host port:

```bash
APP_PORT=8080 docker compose up --build
```

Open <http://localhost:8080>.

## Useful commands

Build the image without starting the service:

```bash
docker compose build
```

Run in the background:

```bash
docker compose up --build -d
```

View logs:

```bash
docker compose logs -f poisson-sor-web
```

Stop and remove the container/network:

```bash
docker compose down
```

Check the health endpoint:

```bash
curl http://localhost:8000/healthz
```

## Runtime configuration

The container uses these environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | Uvicorn bind host inside the container. |
| `PORT` | `8000` | Uvicorn port inside the container. |
| `SOLVER_BINARY_PATH` | `/app/build/poisson_sor` | Internal path to the packaged C++ solver. It is configured only by the deployment environment and is never accepted from browser/API payloads. |
| `MAX_SURFACE_AXIS_POINTS` | `90` | Maximum number of sampled points per axis for server-generated Plotly surfaces. |

The Compose file maps `${APP_PORT:-8000}` on the host to port `8000` inside the container.
