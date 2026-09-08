import { describe, expect, it } from 'vitest'

import { validateDashboardLayout } from '@/lib/dashboardSchema'
import { DASHBOARD_CREATE_TEMPLATES } from '@/lib/dashboardTemplates'

describe('dashboard templates', () => {
  it('pass the frontend dashboard schema', () => {
    for (const template of DASHBOARD_CREATE_TEMPLATES) {
      const errors = validateDashboardLayout(template.layout)
      expect(errors, template.key).toEqual([])
    }
  })
})
