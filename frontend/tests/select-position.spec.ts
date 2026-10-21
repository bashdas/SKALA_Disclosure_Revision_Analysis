import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
test('선택 상자의 위치와 너비가 펼치기 전후에 유지됩니다', async ({ page }) => {
 const {token}=JSON.parse(readFileSync(process.env.E2E_TOKEN_FILE!, 'utf8'))
 await page.addInitScript(t=>sessionStorage.setItem('disclosure-check.token',t),token)
 await page.goto('/companies/00126478?tab=history')
 const trigger=page.locator('.document-section .ui-select')
 await expect(trigger).toBeVisible()
 await expect(page.locator('.company-market-panel .skeleton-state')).toHaveCount(0)
 const metrics=()=>trigger.evaluate(el=>({trigger:el.getBoundingClientRect().toJSON(), parent:el.parentElement?.getBoundingClientRect().toJSON(),children:[...el.parentElement!.children].map(e=>({tag:e.tagName,slot:e.getAttribute('data-slot'),style:e.getAttribute('style'),rect:e.getBoundingClientRect().toJSON()})),bodyStyle:document.body.getAttribute('style')}))
 const before=await metrics()
 await trigger.click()
 await expect(page.getByRole('option',{name:'분석 중',exact:true})).toBeVisible()
 const after=await metrics()

 expect(after.trigger.x).toBe(before.trigger.x)
 expect(after.trigger.width).toBe(before.trigger.width)
 expect(after.trigger.y).toBe(before.trigger.y)
})
