# 项目约定（Claude Code 遵守）

前端（React + TS，`frontend/`）+ 后端（FastAPI，`app/`）一体。以下是协作规范，写代码前先对照。

## 交互与状态（前端）

1. **按钮调接口必须有 loading**：异步操作的按钮在请求期间 `disabled`，文案同步变化（如「保存中…」「提交中…」「执行中…」），防重复提交。不要依赖后端幂等兜底。
2. **提示贴近操作区**：错误/成功信息就近展示在触发它的卡片/抽屉/按钮旁，不要漂到页面很远的位置。局部用 `ErrorBox/SuccessBox`，全局限才用 `toast`。
3. **写操作后刷新数据**：create/update/delete 成功后，`refresh()` 相关列表或重新拉取，保持页面与后端一致。
4. **危险操作二次确认**：删除 / 回滚 / 发布 / 停用等，走 `useConfirm` 或组件内联确认，不直接执行。
5. **空态给下一步**：任何空列表用 `EmptyState` 并给出明确行动（补数据 / 跳转 / 导入）。
6. **筛选/分页联动**：切换筛选条件时重置页码到第 1 页。
7. **表单校验贴近字段**：JSON/必填校验在字段旁即时提示，提交按钮按校验禁用。

## 结构与命名

- 页面私有组件放 `src/pages/<Page>/components/<Name>/index.tsx`；工具函数 `util/`、类型 `type/`、常量 `constants/`；顶层共享放 `src/util`、`src/constants`。不用 `lib`。
- 新页面用统一导出 `index.tsx`。
- CSS 优先 `styles.less`；tailwind 入口 `index.css` 保持 css（工具链限制）。

## 数据与后端

- 长期用 Postgres + alembic 迁移：模型加列 → 立即补迁移文件，别让 create_all 兜底。
- 权限：管理员能力看「管理员/admin」角色，不只看租户级权限；普通用户不应见到管理菜单。
