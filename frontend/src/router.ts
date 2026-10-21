import { createRouter, createWebHistory } from 'vue-router'
import CompaniesView from './views/CompaniesView.vue'
import CompanyView from './views/CompanyView.vue'
import AnalysisView from './views/AnalysisView.vue'
import HomeView from './views/HomeView.vue'
import LoginView from './views/LoginView.vue'
import AccountView from './views/AccountView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/home' },
    { path: '/home', component: HomeView, meta: { title: '내 페이지' } },
    { path: '/disclosures', redirect: '/companies' },
    { path: '/account', component: AccountView, meta: { title: '내 계정' } },
    { path: '/login', component: LoginView, meta: { title: '로그인' } },
    { path: '/companies', component: CompaniesView, meta: { title: '기업 목록' } },
    { path: '/companies/:companyId', component: CompanyView, meta: { title: '기업 리서치' } },
    { path: '/memos', redirect: '/companies' },
    { path: '/analyses', redirect: '/companies' },
    { path: '/analyses/:taskId', component: AnalysisView, meta: { title: '분석 보고서' } },
    { path: '/:pathMatch(.*)*', redirect: '/companies' },
  ],
  scrollBehavior: () => ({ top: 0 }),
})
router.afterEach((to) => {
  document.title = `${String(to.meta.title)}, 공시체크`
})
