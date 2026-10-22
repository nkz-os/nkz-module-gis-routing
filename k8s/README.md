# GIS Routing — Kubernetes manifests

## Image pinning (required before production)

`backend-deployment.yaml` currently references the backend image by `:latest`.
**This must be pinned by digest (`@sha256:...`) before a production rollout.**

Reasons (see root `CLAUDE.md`):
1. `:latest` makes ArgoCD resolve tags non-deterministically, breaking rollback.
2. `:latest` + `imagePullPolicy: Always` caused the complete landing-page outage
   on 2026-05-26.

On merge, CI builds and pushes the backend image (which compiles Fields2Cover from
source). Take the resulting digest and pin it:

```yaml
image: ghcr.io/nkz-os/nkz-module-gis-routing/nkz-module-gis-routing-backend@sha256:<digest>
imagePullPolicy: IfNotPresent
```

## Notes

- The backend image is large (~1.6 GB) because Fields2Cover and OR-Tools are
  compiled and bundled. First pull after a new digest is correspondingly slower —
  account for it in probe `initialDelaySeconds` / rollout timeouts.
