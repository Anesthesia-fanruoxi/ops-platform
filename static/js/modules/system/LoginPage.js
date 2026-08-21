// TOTP 六位验证码组件：6 个独立数字框，填满自动触发 complete；
// 从任意位开始输入自动清空该位之后的格子；支持粘贴分发、Backspace 回退、左右方向键
const TotpCodeInput = {
  name: 'TotpCodeInput',
  props: { modelValue: { type: String, default: '' } },
  emits: ['update:modelValue', 'complete', 'enter'],
  template: `
  <div class="totp-boxes">
    <input v-for="(ch, i) in boxes" :key="i" ref="boxRefs"
      class="totp-box" type="text" inputmode="numeric" autocomplete="one-time-code"
      :value="ch"
      @input="onInput(i, $event)" @keydown="onKeydown(i, $event)"
      @paste="onPaste(i, $event)" @focus="$event.target.select()">
  </div>
  `,
  data() {
    return { boxes: ['', '', '', '', '', ''] };
  },
  watch: {
    // 外部重置（如登录失败清空 code）时同步清空格子
    modelValue(v) {
      const s = String(v || '');
      if (s !== this.boxes.join('')) {
        this.boxes = Array.from({ length: 6 }, (_, k) => s.charAt(k));
      }
    },
  },
  methods: {
    focusBox(i) {
      const els = this.$refs.boxRefs || [];
      if (els[i]) els[i].focus();
    },
    emitValue() {
      const code = this.boxes.join('');
      this.$emit('update:modelValue', code);
      if (code.length === 6) this.$emit('complete', code);
    },
    // 从第 i 格开始填入 digits，并清空 i 之后的所有格子
    fillFrom(i, digits) {
      const next = this.boxes.slice(0, i);
      for (let k = 0; k < digits.length && i + k < 6; k++) next[i + k] = digits[k];
      while (next.length < 6) next.push('');
      this.boxes = next;
    },
    onInput(i, e) {
      const digits = (e.target.value || '').replace(/\D/g, '').slice(0, 6 - i);
      this.fillFrom(i, digits);
      e.target.value = this.boxes[i];
      if (digits.length && i + digits.length < 6) this.focusBox(i + digits.length);
      this.emitValue();
    },
    onPaste(i, e) {
      e.preventDefault();
      const text = (e.clipboardData || window.clipboardData).getData('text') || '';
      const digits = text.replace(/\D/g, '').slice(0, 6 - i);
      if (!digits) return;
      this.fillFrom(i, digits);
      this.focusBox(Math.min(i + digits.length, 5));
      this.emitValue();
    },
    onKeydown(i, e) {
      if (e.key === 'Backspace' && !this.boxes[i]) {
        if (i > 0) {
          e.preventDefault();
          this.boxes[i - 1] = '';
          this.focusBox(i - 1);
          this.emitValue();
        }
      } else if (e.key === 'ArrowLeft' && i > 0) {
        e.preventDefault(); this.focusBox(i - 1);
      } else if (e.key === 'ArrowRight' && i < 5) {
        e.preventDefault(); this.focusBox(i + 1);
      } else if (e.key === 'Enter') {
        this.$emit('enter');
      }
    },
  },
};

// 登录页组件：用户登录（统一鉴权）/ 双因子登录（TOTP）/ 管理员登录（本地密码，仅平台设置）
const LoginPage = {
  compilerOptions: { delimiters: ['[[', ']]'] },
  components: { 'totp-code-input': TotpCodeInput },
  template: `
    <div class="login-wrapper">
      <canvas ref="bgCanvas" class="login-canvas"></canvas>
      <div class="login-orb login-orb-1"></div>
      <div class="login-orb login-orb-2"></div>
      <div class="login-orb login-orb-3"></div>
      <div class="login-card">
        <div class="login-title">运维平台</div>
        <div class="login-title-en">OPS PLATFORM</div>

        <!-- 双因子第二步（ticket 模式）：认证中心多步登录要求二次验证 -->
        <template v-if="twoFa">
          <div class="login-subtitle">双因子验证</div>
          <el-form label-position="top">
            <el-form-item label="验证码">
              <totp-code-input v-model="twoFaCode" @complete="handleTwoFa" @enter="handleTwoFa"></totp-code-input>
            </el-form-item>
            <el-form-item>
              <button class="login-btn" :disabled="loading" @click.prevent="handleTwoFa">
                [[ loading ? '验证中...' : '验 证' ]]
              </button>
            </el-form-item>
          </el-form>
          <div class="login-back" @click="backFromTwoFa">← 返回重新登录</div>
        </template>

        <template v-else>
          <div class="login-tabs">
            <button class="login-tab" :class="{active: activeTab==='user'}" @click="switchTab('user')">用户登录</button>
            <button class="login-tab" :class="{active: activeTab==='totp'}" @click="switchTab('totp')">双因子登录</button>
            <button class="login-tab" :class="{active: activeTab==='admin'}" @click="switchTab('admin')">管理员登录</button>
          </div>

          <!-- 用户登录：统一账号（authPlatform 校验，未接入时本地账号） -->
          <div v-if="activeTab==='user'">
            <el-form :model="form" :rules="rules" ref="formRef" label-position="top">
              <el-form-item label="用户名" prop="username">
                <el-input v-model="form.username" placeholder="请输入用户名"
                  prefix-icon="User" @keyup.enter="handleLogin"></el-input>
              </el-form-item>
              <el-form-item label="密码" prop="password">
                <el-input v-model="form.password" type="password" placeholder="请输入密码"
                  prefix-icon="Lock" show-password @keyup.enter="handleLogin"></el-input>
              </el-form-item>
              <el-form-item>
                <button class="login-btn" :disabled="loading" @click.prevent="handleLogin">
                  [[ loading ? '登录中...' : '登 录' ]]
                </button>
              </el-form-item>
            </el-form>
          </div>

          <!-- 双因子登录：用户名 + TOTP 验证码（无需密码，认证中心按 totp 登录类型校验） -->
          <div v-else-if="activeTab==='totp'">
            <el-form :model="totpForm" :rules="totpRules" ref="totpFormRef" label-position="top">
              <el-form-item label="用户名" prop="username">
                <el-input v-model="totpForm.username" placeholder="请输入用户名"
                  prefix-icon="User" @keyup.enter="handleTotpLogin"></el-input>
              </el-form-item>
              <el-form-item label="TOTP 验证码" prop="code">
                <totp-code-input v-model="totpForm.code" @complete="handleTotpLogin" @enter="handleTotpLogin"></totp-code-input>
              </el-form-item>
              <el-form-item>
                <button class="login-btn" :disabled="loading" @click.prevent="handleTotpLogin">
                  [[ loading ? '登录中...' : '登 录' ]]
                </button>
              </el-form-item>
            </el-form>
          </div>

          <!-- 管理员登录：超级管理员（本地账号），仅用于平台设置 -->
          <div v-else>
            <el-form :model="adminForm" :rules="adminRules" ref="adminFormRef" label-position="top">
              <el-form-item label="超级管理员账号" prop="username">
                <el-input v-model="adminForm.username" placeholder="请输入超级管理员账号"
                  prefix-icon="User" @keyup.enter="handleAdminLogin"></el-input>
              </el-form-item>
              <el-form-item label="密码" prop="password">
                <el-input v-model="adminForm.password" type="password" placeholder="请输入超级管理员密码"
                  prefix-icon="Lock" show-password @keyup.enter="handleAdminLogin"></el-input>
              </el-form-item>
              <el-form-item>
                <button class="login-btn" :disabled="loading" @click.prevent="handleAdminLogin">
                  [[ loading ? '登录中...' : '管理员登录' ]]
                </button>
              </el-form-item>
            </el-form>
          </div>
        </template>

        <div class="login-footer">安全 · 稳定 · 高效</div>
      </div>
    </div>
  `,
  setup() {
    const formRef = Vue.ref(null);
    const adminFormRef = Vue.ref(null);
    const totpFormRef = Vue.ref(null);
    const form = Vue.reactive({ username: '', password: '' });
    const adminForm = Vue.reactive({ username: '', password: '' });
    const totpForm = Vue.reactive({ username: '', code: '' });
    const loading = Vue.ref(false);
    const activeTab = Vue.ref('user');
    // 双因子第二步状态（认证中心多步登录）
    const twoFa = Vue.ref(false);
    const twoFaTicket = Vue.ref('');
    const twoFaCode = Vue.ref('');

    // ── 粒子星空背景（实例级生命周期，组件销毁即停止；函数声明在 setup 内不污染全局作用域）──
    const bgCanvas = Vue.ref(null);
    let stopParticles = null;

    function startLoginParticles(canvas) {
      if (!canvas || !canvas.getContext) return null;
      const ctx = canvas.getContext('2d');
      let raf = 0;
      let running = true;
      let dots = [];
      const COLORS = ['64,220,255', '90,170,255', '150,130,255', '0,220,200'];
      // 鼠标交互状态（声明在函数作用域：resize/tick/清理闭包共享，避免 resize 内局部变量被外层引用报 ReferenceError）
      let mouse = { x: -9999, y: -9999 };
      const MAX_TRAIL = 30;
      let trail = [];
      let dragging = false;
      let fading = false;
      // ── 鼠标拖拽光线（按住拖动产生拖尾光效，释放渐隐） ──
      const getPos = (e) => {
        const r = canvas.getBoundingClientRect();
        return { x: e.clientX - r.left, y: e.clientY - r.top };
      };
      const onDown = (e) => { dragging = true; fading = false; trail = [{ ...getPos(e), a: 1 }]; };
      const onMove = (e) => {
        const pos = getPos(e);
        mouse = pos;
        if (!dragging) return;
        trail.push({ ...pos, a: 1 });
        if (trail.length > MAX_TRAIL) trail.shift();
      };
      const onLeave = () => { mouse = { x: -9999, y: -9999 }; };
      const onUp = () => { dragging = false; fading = true; };
      window.addEventListener('mousedown', onDown);
      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
      window.addEventListener('mouseleave', onLeave);

      function resize() {
        canvas.width = canvas.offsetWidth;
        canvas.height = canvas.offsetHeight;
        const n = Math.min(130, Math.floor(canvas.width * canvas.height / 13000));
        dots = Array.from({ length: n }, () => ({
          x: Math.random() * canvas.width,
          y: Math.random() * canvas.height,
          vx: (Math.random() - 0.5) * 0.35,
          vy: (Math.random() - 0.5) * 0.35,
          r: Math.random() * 1.6 + 0.6,
          c: COLORS[Math.floor(Math.random() * COLORS.length)],
        }));
      }
      function tick() {
        if (!running) return;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        // 粒子：移动 + 鼠标吸引（hover 轻微聚拢，拖拽增强）+ 发光
        for (const d of dots) {
          d.x += d.vx; d.y += d.vy;
          if (d.x < 0 || d.x > canvas.width) d.vx *= -1;
          if (d.y < 0 || d.y > canvas.height) d.vy *= -1;
          if (mouse.x > -1000) {
            const ddx = mouse.x - d.x, ddy = mouse.y - d.y;
            const dd = Math.sqrt(ddx * ddx + ddy * ddy);
            if (dd < 230) {
              const pull = (dragging ? 0.022 : 0.009) * (1 - dd / 230);
              d.x += ddx * pull;
              d.y += ddy * pull;
            }
          }
          // 发光点（大粒子带光晕）
          if (d.r > 1.3) {
            const halo = ctx.createRadialGradient(d.x, d.y, 0, d.x, d.y, d.r * 5);
            halo.addColorStop(0, 'rgba(' + d.c + ',0.35)');
            halo.addColorStop(1, 'rgba(' + d.c + ',0)');
            ctx.fillStyle = halo;
            ctx.beginPath();
            ctx.arc(d.x, d.y, d.r * 5, 0, Math.PI * 2);
            ctx.fill();
          }
          ctx.beginPath();
          ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(' + d.c + ',0.85)';
          ctx.fill();
        }
        // 邻近粒子连线（网络感；靠近鼠标的连线更亮）
        for (let i = 0; i < dots.length; i++) {
          for (let j = i + 1; j < dots.length; j++) {
            const dx = dots[i].x - dots[j].x, dy = dots[i].y - dots[j].y;
            const dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < 130) {
              const base = 0.2 * (1 - dist / 130);
              let boost = 0;
              if (mouse.x > -1000) {
                const dm1 = Math.sqrt((dots[i].x - mouse.x) ** 2 + (dots[i].y - mouse.y) ** 2);
                const dm2 = Math.sqrt((dots[j].x - mouse.x) ** 2 + (dots[j].y - mouse.y) ** 2);
                if (dm1 < 180 || dm2 < 180) boost = 0.25;
              }
              ctx.strokeStyle = 'rgba(110,200,255,' + Math.min(0.55, base + boost).toFixed(3) + ')';
              ctx.lineWidth = 1;
              ctx.beginPath();
              ctx.moveTo(dots[i].x, dots[i].y);
              ctx.lineTo(dots[j].x, dots[j].y);
              ctx.stroke();
            }
          }
        }
        // 鼠标拖拽光线绘制
        if (trail.length > 1) {
          for (let i = 1; i < trail.length; i++) {
            const pa = trail[i - 1], pb = trail[i];
            const alpha = (pa.a || 1) * (i / trail.length) * 0.55;
            ctx.strokeStyle = 'rgba(140, 190, 255, ' + alpha.toFixed(3) + ')';
            ctx.lineWidth = Math.max(0.6, i * 0.55);
            ctx.lineCap = 'round';
            ctx.beginPath();
            ctx.moveTo(pa.x, pa.y);
            ctx.lineTo(pb.x, pb.y);
            ctx.stroke();
          }
          const last = trail[trail.length - 1];
          const grd = ctx.createRadialGradient(last.x, last.y, 0, last.x, last.y, 30);
          grd.addColorStop(0, 'rgba(160, 205, 255, 0.85)');
          grd.addColorStop(1, 'rgba(160, 205, 255, 0)');
          ctx.fillStyle = grd;
          ctx.beginPath();
          ctx.arc(last.x, last.y, 30, 0, Math.PI * 2);
          ctx.fill();
        }
        // 释放后光线渐隐消失
        if (fading && trail.length) {
          trail.forEach(p => { p.a = (p.a || 1) * 0.90; });
          trail = trail.filter(p => (p.a || 0) > 0.03);
          if (!trail.length) fading = false;
        }

        raf = requestAnimationFrame(tick);
      }
      resize();
      tick();
      window.addEventListener('resize', resize);
      return function () {
        running = false;
        cancelAnimationFrame(raf);
        window.removeEventListener('resize', resize);
        window.removeEventListener('mousedown', onDown);
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
        window.removeEventListener('mouseleave', onLeave);
      };
    }

    Vue.onMounted(() => { stopParticles = startLoginParticles(bgCanvas.value); });
    Vue.onUnmounted(() => { if (stopParticles) stopParticles(); });

    const rules = {
      username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
      password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
    };
    const adminRules = {
      username: [{ required: true, message: '请输入超级管理员账号', trigger: 'blur' }],
      password: [{ required: true, message: '请输入管理员密码', trigger: 'blur' }],
    };
    const totpRules = {
      username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
      code: [{ required: true, message: '请输入 TOTP 验证码', trigger: 'blur' }],
    };

    function switchTab(tab) {
      activeTab.value = tab;
      loading.value = false;
      twoFa.value = false;
      twoFaTicket.value = '';
      twoFaCode.value = '';
    }

    // 登录成功后的统一处理：保存 token、更新全局状态、按角色跳转
    function onLoginSuccess(res) {
      localStorage.setItem('auth_token', res.data.token);
      localStorage.setItem('auth_expires', res.data.expires_at);

      authState.isLoggedIn = true;
      authState.username = res.data.user.username;
      authState.nickname = res.data.user.nickname || '';
      authState.roleName = res.data.user.role_name || '';
      authState.permissions = res.data.user.permissions || [];
      authState.isSuperAdmin = !!res.data.user.is_super_admin;
      // 同步密码策略（登录响应携带，供修改密码弹窗的随机密码生成与前端校验使用）
      if (res.data.password_policy) authState.passwordPolicy = res.data.password_policy;

      // 登录跳转：带路径请求（如直链 /settings）登录后跳回原菜单；否则一律首页
      const redirect = router.currentRoute.value.query.redirect;
      if (redirect && redirect.startsWith('/') && redirect !== '/login') {
        router.push(redirect);
      } else {
        router.push('/dashboard');
      }
    }

    const handleLogin = async () => {
      if (!formRef.value) return;
      try {
        await formRef.value.validate();
      } catch (e) {
        return;
      }

      loading.value = true;
      ajax('POST', '/api/auth/login', {
        username: form.username,
        password: form.password,
      }, (res) => {
        loading.value = false;
        if (res.code === 200) {
          if (res.data && res.data.require_2fa) {
            // 认证中心要求双因子：进入验证码步骤（ticket 为认证中心多步登录票据）
            twoFaTicket.value = res.data.ticket || '';
            twoFaCode.value = '';
            twoFa.value = true;
            Vue.nextTick(() => {
              const el = document.querySelector('.login-card input');
              if (el) el.focus();
            });
            return;
          }
          onLoginSuccess(res);
        } else {
          ElementPlus.ElMessage.error(res.msg || '登录失败');
        }
      });
    };

    // TOTP 双因子登录（免密码）：用户名 + 验证码提交，后端透传认证中心按 totp 类型校验
    const handleTotpLogin = async () => {
      if (!totpFormRef.value) return;
      try {
        await totpFormRef.value.validate();
      } catch (e) {
        return;
      }

      loading.value = true;
      ajax('POST', '/api/auth/login', {
        username: totpForm.username,
        code: totpForm.code,
      }, (res) => {
        loading.value = false;
        if (res.code === 200) {
          if (res.data && res.data.require_2fa) {
            ElementPlus.ElMessage.error('验证码已失效，请重新登录');
            resetCodeBoxes(() => { totpForm.code = ''; });
            return;
          }
          onLoginSuccess(res);
        } else {
          ElementPlus.ElMessage.error(res.msg || '登录失败');
          resetCodeBoxes(() => { totpForm.code = ''; });
        }
      });
    };

    // 双因子第二步：ticket + 验证码提交认证中心校验（平台不验码）
    const handleTwoFa = () => {
      const code = String(twoFaCode.value || '').trim();
      if (!code) {
        ElementPlus.ElMessage.warning('请输入验证码');
        return;
      }
      loading.value = true;
      ajax('POST', '/api/auth/login-2fa', {
        ticket: twoFaTicket.value,
        code: code,
      }, (res) => {
        loading.value = false;
        if (res.code === 200) {
          onLoginSuccess(res);
        } else {
          ElementPlus.ElMessage.error(res.msg || '验证失败');
          resetCodeBoxes(() => { twoFaCode.value = ''; });
        }
      });
    };

    // 登录/验证失败后清空验证码并聚焦第一个格子，便于直接重输
    function resetCodeBoxes(clearFn) {
      clearFn();
      Vue.nextTick(() => {
        const el = document.querySelector('.totp-box');
        if (el) el.focus();
      });
    }

    const backFromTwoFa = () => {
      twoFa.value = false;
      twoFaTicket.value = '';
      twoFaCode.value = '';
    };

    const handleAdminLogin = async () => {
      if (!adminFormRef.value) return;
      try {
        await adminFormRef.value.validate();
      } catch (e) {
        return;
      }

      loading.value = true;
      ajax('POST', '/api/auth/admin-login', {
        username: adminForm.username,
        password: adminForm.password,
      }, (res) => {
        loading.value = false;
        if (res.code === 200) {
          onLoginSuccess(res);
        } else {
          ElementPlus.ElMessage.error(res.msg || '登录失败');
        }
      });
    };

    return {
      formRef, adminFormRef, totpFormRef, form, adminForm, totpForm,
      loading, activeTab, rules, adminRules, totpRules, bgCanvas,
      twoFa, twoFaCode, switchTab, handleLogin, handleAdminLogin,
      handleTotpLogin, handleTwoFa, backFromTwoFa,
    };
  }
};
