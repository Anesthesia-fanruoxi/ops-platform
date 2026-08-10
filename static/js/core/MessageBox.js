// 通用消息提示组件
const MessageBox = {
  template: `
    <div v-if="visible" class="message-mask" @click.self="close">
      <div class="message-box" :class="'message-' + type">
        <div class="message-header">
          <span class="message-icon">{{ icon }}</span>
          <span class="message-title">{{ title }}</span>
        </div>
        <div class="message-content">{{ content }}</div>
        <div class="message-footer">
          <button v-if="showCancel" class="btn btn-default" @click="cancel">取消</button>
          <button class="btn" :class="btnClass" @click="confirm">确定</button>
        </div>
      </div>
    </div>
  `,
  props: {
    visible: { type: Boolean, default: false },
    type: { type: String, default: 'info' }, // info, success, warning, error
    title: { type: String, default: '提示' },
    content: { type: String, default: '' },
    showCancel: { type: Boolean, default: false }
  },
  computed: {
    icon() {
      const icons = { info: 'ℹ️', success: '✅', warning: '⚠️', error: '❌' };
      return icons[this.type] || 'ℹ️';
    },
    btnClass() {
      const classes = { info: 'btn-primary', success: 'btn-success', warning: 'btn-warning', error: 'btn-danger' };
      return classes[this.type] || 'btn-primary';
    }
  },
  methods: {
    confirm() {
      this.$emit('confirm');
      this.$emit('update:visible', false);
    },
    cancel() {
      this.$emit('cancel');
      this.$emit('update:visible', false);
    },
    close() {
      this.$emit('update:visible', false);
    }
  }
};

// 全局消息提示函数
function showMessage(options) {
  return new Promise((resolve) => {
    const { type = 'info', title = '提示', content = '', showCancel = false } = options;

    // 创建容器
    const container = document.createElement('div');
    container.id = 'message-box-container';
    document.body.appendChild(container);

    // 创建Vue实例
    const app = Vue.createApp({
      template: `
        <MessageBox
          :visible="visible"
          :type="type"
          :title="title"
          :content="content"
          :showCancel="showCancel"
          @confirm="handleConfirm"
          @cancel="handleCancel"
        />
      `,
      components: { MessageBox },
      data() {
        return {
          visible: true,
          type,
          title,
          content,
          showCancel
        };
      },
      methods: {
        handleConfirm() {
          resolve(true);
          this.destroy();
        },
        handleCancel() {
          resolve(false);
          this.destroy();
        },
        destroy() {
          this.visible = false;
          setTimeout(() => {
            this.$destroy();
            container.remove();
          }, 300);
        }
      }
    });

    app.mount(container);
  });
}

// 便捷函数
async function showInfo(content, title = '提示') {
  return showMessage({ type: 'info', title, content });
}

async function showSuccess(content, title = '成功') {
  return showMessage({ type: 'success', title, content });
}

async function showWarning(content, title = '警告') {
  return showMessage({ type: 'warning', title, content });
}

async function showError(content, title = '错误') {
  return showMessage({ type: 'error', title, content });
}

async function showConfirm(content, title = '确认') {
  return showMessage({ type: 'warning', title, content, showCancel: true });
}
