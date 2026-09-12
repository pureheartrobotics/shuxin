<template>
  <scroll-view class="legal-page" scroll-y>
    <view class="legal-body">
      <view class="legal-title">稚子心机器人用户服务协议</view>
      <view class="legal-updated">更新日期：2026年7月3日</view>

      <view class="section">
        <view class="section-text">
          欢迎使用稚子心机器人小程序。本协议由深圳市稚子心机器人科技有限公司（以下简称「我们」）与使用本小程序的用户（以下简称「你」）共同订立。请你在使用前仔细阅读本协议全部内容。
        </view>
      </view>

      <view class="section">
        <view class="section-heading">一、服务内容</view>
        <view class="section-text">
          本小程序提供稚子心陪伴机器人的设备绑定、设备管理、蓝牙配网、账户时长查询与充值、意见反馈等功能。具体功能以小程序实际提供为准。
        </view>
      </view>

      <view class="section">
        <view class="section-heading">二、账号与登录</view>
        <view class="section-text">
          你可通过微信授权登录使用本小程序。登录仅用于确认设备归属关系及提供相关服务，我们不会将你的微信账号密码用于其他用途。
        </view>
      </view>

      <view class="section">
        <view class="section-heading">三、设备绑定与使用</view>
        <view class="section-text">
          你应通过合法途径获取设备认领码并完成绑定。绑定成功后，设备将与当前微信用户账号关联。你应妥善保管设备，并对绑定后设备的使用行为负责。
        </view>
      </view>

      <view class="section">
        <view class="section-heading">四、付费服务</view>
        <view class="section-text">
          部分功能可能涉及账户时长充值等付费服务。你通过微信支付完成付款后，相应权益将计入你的账户。除法律法规另有规定外，虚拟服务一经购买不支持无理由退款。
        </view>
      </view>

      <view class="section">
        <view class="section-heading">五、用户行为规范</view>
        <view class="section-text">
          你不得利用本小程序从事违法违规活动，不得干扰小程序正常运行，不得尝试未经授权访问系统或他人数据。
        </view>
      </view>

      <view class="section">
        <view class="section-heading">六、隐私保护</view>
        <view class="section-text">
          我们重视你的个人信息保护。关于个人信息的收集、使用、存储及你的权利，请查阅《隐私政策》/《隐私保护指引》。
        </view>
      </view>

      <view class="section">
        <view class="section-heading">七、免责声明</view>
        <view class="section-text">
          因网络状况、设备故障、不可抗力等导致的服务中断或数据丢失，我们将在合理范围内协助处理，但不承担超出法律规定范围的责任。
        </view>
      </view>

      <view class="section">
        <view class="section-heading">八、协议变更</view>
        <view class="section-text">
          我们可能适时修订本协议。修订后将通过小程序内公告或其他合理方式通知你。若你继续使用本小程序，即视为你接受修订后的协议。
        </view>
      </view>

      <view class="section">
        <view class="section-heading">九、联系我们</view>
        <view class="section-text">
          如对本协议有任何疑问，请通过以下方式联系我们：
        </view>
        <view class="contact">邮箱：1184429115@qq.com</view>
      </view>
    </view>
  </scroll-view>
</template>

<style scoped>
.legal-page {
  height: 100vh;
  background: #f5f1ea;
}

.legal-body {
  padding: 36rpx 34rpx 80rpx;
}

.legal-title {
  color: #24211c;
  font-size: 40rpx;
  font-weight: 700;
  line-height: 1.35;
}

.legal-updated {
  color: #82786d;
  font-size: 24rpx;
  margin-top: 12rpx;
  margin-bottom: 28rpx;
}

.section {
  margin-bottom: 32rpx;
}

.section-heading {
  color: #25211c;
  font-size: 30rpx;
  font-weight: 700;
  margin-bottom: 14rpx;
}

.section-text {
  color: #4a443c;
  font-size: 28rpx;
  line-height: 1.75;
  margin-bottom: 12rpx;
}

.contact {
  color: #2f604f;
  font-size: 28rpx;
  font-weight: 600;
  margin-top: 8rpx;
}
</style>
