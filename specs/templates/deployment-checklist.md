# Deployment Checklist

<!-- PROJECT: Replace this template with your project-specific deployment
     checklists. Create one section per deployable component (backend, frontend,
     etc.) with the specific checks for your infrastructure. -->

Use this checklist before every deployment. Complete the relevant section(s) for what is being deployed.

---

## Backend

*Complete for every backend deployment.*

### Tests & Quality
- [ ] All tests pass
- [ ] Linter passes with zero errors
- [ ] No new warnings introduced

### Database
- [ ] Database migrations applied and tested locally
- [ ] No destructive migration without backup plan

### Environment
- [ ] All required environment variables documented
- [ ] No secrets in code — secrets injected at deploy time

### Deployment
- [ ] Feature branch pushed
- [ ] PR created with summary + test plan
- [ ] Post-deploy smoke test defined

### Manifest
- [ ] Task status updated to `done` in `manifest.yaml`
- [ ] Manifest commit is separate from code commits

---

## Frontend

*Complete for every frontend deployment.*

### Tests & Quality
- [ ] All tests pass
- [ ] Linter passes
- [ ] No console errors in browser

### Build
- [ ] Production build succeeds
- [ ] No hardcoded API URLs — environment variables used

### Deployment
- [ ] Feature branch pushed
- [ ] PR created with summary + test plan
- [ ] Post-deploy smoke test: app loads, auth flow works, core feature functional

### Manifest
- [ ] Task status updated to `done` in `manifest.yaml`
- [ ] Manifest commit is separate from code commits

---

## Adding New Sections

When a new deployable component is introduced, add a section following this pattern:
1. Tests & Quality gate
2. Component-specific checks
3. Environment verification
4. Deployment steps
5. Manifest update
