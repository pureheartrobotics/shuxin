<template>
  <scroll-view class="legal-page" scroll-y>
    <view class="legal-body">
      <view class="legal-title">稚子心机器人小程序隐私保护指引</view>
      <view class="legal-updated">更新日期：2026年7月3日</view>

      <view class="section">
        <view class="section-text">
          本指引是稚子心机器人小程序开发者深圳市稚子心机器人科技有限公司（以下简称「开发者」）为处理你的个人信息而制定。
        </view>
      </view>

      <view class="section">
        <view class="section-heading">一、开发者处理的信息</view>
        <view class="section-text">
          根据法律规定，开发者仅处理实现小程序功能所必要的信息。
        </view>
        <view class="section-list">
          <view class="list-item">
            开发者将在获取你的明示同意后，访问你的摄像头，用途是：仅用于扫描或识别设备外壳条形码，识别后即用于绑定，不在本地长期保存。
          </view>
          <view class="list-item">
            开发者将在获取你的明示同意后，收集你的手机号，用途是：用户自愿填写，用于反馈问题后联系。
          </view>
          <view class="list-item">
            开发者访问你的蓝牙，用途是：通过低功耗蓝牙（BLE）连接处于配网模式的设备，并向设备发送 Wi-Fi 账号密码以完成网络配置。
          </view>
          <view class="list-item">
            开发者将在获取你的明示同意后，访问你的位置信息，用途是：在 Android 系统上扫描附近蓝牙设备需申请位置权限；本小程序不采集、不上传 GPS 坐标。
          </view>
          <view class="list-item">
            开发者通过已连接设备扫描附近 2.4GHz 无线网络名称（SSID），用于向设备发送配网信息；不读取手机 Wi-Fi 列表，不调用手机端 Wi-Fi 接口。
          </view>
        </view>
      </view>

      <view class="section">
        <view class="section-heading">二、第三方插件信息 / SDK 信息</view>
        <view class="section-text">
          为实现特定功能，开发者可能会接入由第三方提供的插件/SDK。第三方插件/SDK 的个人信息处理规则，请以其公示的官方说明为准。
        </view>
      </view>

      <view class="section">
        <view class="section-heading">三、未成年人保护</view>
        <view class="section-text">
          根据相关法律法规的规定，若你是 14 周岁以下的未成年人，你需要和你的监护人共同仔细阅读本指引，并在征得监护人明示同意后继续使用小程序服务。开发者将根据相关法律法规的规定及本指引内容，处理经监护人同意而收集的未成年人用户信息，并通过本指引「你的权益」部分披露的内容保障未成年人在个人信息处理活动中的各项权利。
        </view>
      </view>

      <view class="section">
        <view class="section-heading">四、你的权益</view>
        <view class="section-text">
          关于你的个人信息，你可以通过以下方式与开发者联系，行使查阅、复制、更正、删除等法定权利。
        </view>
        <view class="section-text">
          若你在小程序中注册了账号，你可以通过以下方式与开发者联系，申请注销你在小程序中使用的账号。在受理你的申请后，开发者承诺在十五个工作日内完成核查和处理，并按照法律法规要求处理你的相关信息。
        </view>
        <view class="contact">联系邮箱：1184429115@qq.com</view>
      </view>

      <view class="section">
        <view class="section-heading">五、开发者对信息的存储</view>
        <view class="section-text">
          开发者承诺，除法律法规另有规定外，开发者对你的信息的保存期限应当为实现处理目的所必要的最短时间。
        </view>
      </view>

      <view class="section">
        <view class="section-heading">六、信息的使用规则</view>
        <view class="section-text">
          开发者将会在本指引所明示的用途内使用收集的信息。
        </view>
        <view class="section-text">
          如开发者使用你的信息超出本指引目的或合理范围，开发者必须在变更使用目的或范围前，再次以邮件方式告知并征得你的明示同意。
        </view>
      </view>

      <view class="section">
        <view class="section-heading">七、信息对外提供</view>
        <view class="section-text">
          开发者承诺，不会主动共享或转让你的信息至任何第三方，如存在确需共享或转让时，开发者应当直接征得或确认第三方征得你的单独同意。
        </view>
        <view class="section-text">
          开发者承诺，不会对外公开披露你的信息，如必须公开披露时，开发者应当向你告知公开披露的目的、披露信息的类型及可能涉及的信息，并征得你的单独同意。
        </view>
      </view>

      <view class="section">
        <view class="section-heading">八、投诉与联系</view>
        <view class="section-text">
          你认为开发者未遵守上述约定，或有其他的投诉建议、或未成年人个人信息保护相关问题，可通过以下方式与开发者联系；或者向微信进行投诉。
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

.section-list {
  margin-top: 8rpx;
}

.list-item {
  color: #4a443c;
  font-size: 28rpx;
  line-height: 1.75;
  padding-left: 24rpx;
  margin-bottom: 12rpx;
  position: relative;
}

.list-item::before {
  content: "•";
  position: absolute;
  left: 0;
  color: #2f604f;
}

.contact {
  color: #2f604f;
  font-size: 28rpx;
  font-weight: 600;
  margin-top: 8rpx;
}
</style>
