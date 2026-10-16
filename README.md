### Eye CRM

Deals, costing, pricing, approvals and billing for Eye Advertising, on ERPNext v16.

The old app lives on the `v1` branch as `eye_crm_v1`.

### Install

```bash
bench get-app --branch main https://github.com/KamalAdel91/eye_crm
bench --site SITE install-app eye_crm
```

### Tests

```bash
bench --site TEST_SITE set-config allow_tests true
bench --site TEST_SITE run-tests --app eye_crm
```

### License

mit
