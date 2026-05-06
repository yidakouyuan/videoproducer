import registerTagTools from "./tools/tag";
import registerMediaTools from "./tools/media";
import registerVideoTools from "./tools/video";
import registerTranscribeTools from "./tools/transcribe";
import registerVideoGenerateTools from "./tools/video_generate";
import registerImageGenerateTools from "./tools/image_generate";
import registerStatsTools from "./tools/stats";
import registerFsTools from "./tools/fs";
import registerStageVideoTool from "./tools/stage_video";
import registerWebTools from "./tools/web";

export default function (api: any) {
  registerTagTools(api);
  registerMediaTools(api);
  registerVideoTools(api);
  registerTranscribeTools(api);
  registerVideoGenerateTools(api);
  registerImageGenerateTools(api);
  registerStatsTools(api);
  registerFsTools(api);
  registerStageVideoTool(api);
  registerWebTools(api);
}
