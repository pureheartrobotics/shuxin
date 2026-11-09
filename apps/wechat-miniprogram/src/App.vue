<script>
import { captureEnterOptions, captureLaunchQuery } from "./core/first-meet";

export default {
  onLaunch(options) {
    captureLaunchQuery(options && options.query);
    captureEnterOptions();
  },
  onShow(options) {
    captureLaunchQuery(options && options.query);
    captureEnterOptions();
  },
};
</script>

<style>
page {
  min-height: 100%;
  background: #f5f1ea;
  color: #24211c;
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
}

button {
  border-radius: 999rpx;
}
</style>
