# Custom domains (PRD R11, D10): prod app only; staging stays on *.web.app.
# DNS is added by the owner after apply (output required_dns_updates), so do not block apply on verification.
resource "google_firebase_hosting_custom_domain" "app" {
  provider              = google-beta
  project               = var.project
  site_id               = google_firebase_hosting_site.app.site_id
  custom_domain         = "app.onolys.com"
  wait_dns_verification = false
}

# Admin domain (SP07, after launch): gated by var.admin_enabled.
resource "google_firebase_hosting_custom_domain" "admin" {
  count                 = var.admin_enabled ? 1 : 0
  provider              = google-beta
  project               = var.project
  site_id               = google_firebase_hosting_site.admin[0].site_id
  custom_domain         = "admin.onolys.com"
  wait_dns_verification = false
}

locals {
  custom_domains = merge(
    { "app.onolys.com" = google_firebase_hosting_custom_domain.app },
    { for d in google_firebase_hosting_custom_domain.admin : "admin.onolys.com" => d },
  )
}

# Exact DNS records the owner must add: one entry per record, flattened from Hosting's desired state
# (site routing records) plus the certificate DNS challenge (_acme-challenge TXT) when Hosting asks for it.
output "required_dns_updates" {
  description = "DNS records to add at the registrar (type, host, value). Empty for a domain once Hosting needs nothing more."
  value = flatten([
    for domain, d in local.custom_domains : concat(
      flatten([
        for u in d.required_dns_updates : [
          for dd in u.desired : [
            for r in dd.records : {
              domain = domain
              type   = r.type
              host   = r.domain_name
              value  = r.rdata
              action = r.required_action
            }
          ]
        ]
      ]),
      flatten([
        for c in d.cert : [
          for v in c.verification : [
            for dn in v.dns : [
              for dd in dn.desired : [
                for r in dd.records : {
                  domain = domain
                  type   = r.type
                  host   = r.domain_name
                  value  = r.rdata
                  action = r.required_action
                }
              ]
            ]
          ]
        ]
      ]),
    )
  ])
}

output "custom_domain_status" {
  description = "Hosting verification state per custom domain (expect ownership OWNERSHIP_ACTIVE, host HOST_ACTIVE, cert CERT_ACTIVE after DNS)."
  value = {
    for domain, d in local.custom_domains : domain => {
      ownership = d.ownership_state
      host      = d.host_state
      cert      = try(d.cert[0].state, null)
    }
  }
}
