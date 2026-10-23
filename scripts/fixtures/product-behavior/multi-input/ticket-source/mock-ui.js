// Frozen simulated UI baseline; author: Jeff.Liu. Not a production implementation.
export const ticketList = { filter: ['状态'], toolbar: ['查询', '重置'], columns: ['工单号', '客户名称', '状态', '操作'], overflow: 'tooltip' };
export const ticketDetail = { fields: ['工单号', '客户名称', '状态'], actions: ['保存', '取消'] };
export const canEdit = ticket => ticket.status === '待处理';
export const saveBaseline = ticket => ({ ...ticket });
