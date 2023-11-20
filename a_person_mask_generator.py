from functools import reduce
import cv2
import gradio as gr
import os
from PIL import Image
import wget
import numpy as np
import mediapipe as mp

import modules.scripts as scripts

BaseOptions = mp.tasks.BaseOptions
ImageSegmenter = mp.tasks.vision.ImageSegmenter
ImageSegmenterOptions = mp.tasks.vision.ImageSegmenterOptions
VisionRunningMode = mp.tasks.vision.RunningMode

MASK_OPTION_0_BACKGROUND = 'background'
MASK_OPTION_1_HAIR = 'hair'
MASK_OPTION_2_BODY = 'body (skin)'
MASK_OPTION_3_FACE = 'face (skin)'
MASK_OPTION_4_CLOTHES = 'clothes'

title = "A Person Mask Generator"


class Script(scripts.Script):

    def __init__(self):
        self.img2img: gr.Image = None

    def title(self):
        return title

    def show(self, is_img2img):
        return scripts.AlwaysVisible


    def get_mediapipe_image(self, image: Image) -> mp.Image:
        # Convert gr.Image to NumPy array
        numpy_image = np.asarray(image)

        image_format = mp.ImageFormat.SRGB

        # Convert BGR to RGB (if necessary)
        if numpy_image.shape[-1] == 4:
            image_format = mp.ImageFormat.SRGBA
        elif numpy_image.shape[-1] == 3:
            image_format = mp.ImageFormat.SRGB
            numpy_image = cv2.cvtColor(numpy_image, cv2.COLOR_BGR2RGB)

        return mp.Image(image_format=image_format, data=numpy_image)

    def generate_mask(self, image: Image, mask_targets: list[str]) -> Image:
        if image is None or len(mask_targets) <= 0:
            return None
        model_folder_path = os.path.join('models', 'mediapipe')
        os.makedirs(model_folder_path, exist_ok=True)

        model_path = os.path.join(model_folder_path, 'selfie_multiclass_256x256.tflite')
        if not os.path.exists(model_path):
            print("Downloading 'selfie_multiclass_256x256.tflite' model")
            model_url = 'https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite'
            wget.download(model_url, model_path)

        options = ImageSegmenterOptions(base_options=BaseOptions(model_asset_path=model_path),
                                        running_mode=VisionRunningMode.IMAGE,
                                        output_category_mask=True)
            # Create the image segmenter
        with ImageSegmenter.create_from_options(options) as segmenter:

            # Retrieve the masks for the segmented image
            media_pipe_image = self.get_mediapipe_image(image=image)
            segmented_masks = segmenter.segment(media_pipe_image)

            masks = []
            for i, target in enumerate(mask_targets):
                # https://developers.google.com/mediapipe/solutions/vision/image_segmenter#multiclass-model
                # 0 - background
                # 1 - hair
                # 2 - body - skin
                # 3 - face - skin
                # 4 - clothes
                # 5 - others(accessories)
                mask_index = 0
                if target == MASK_OPTION_1_HAIR:
                    mask_index = 1
                if target == MASK_OPTION_2_BODY:
                    mask_index = 2
                if target == MASK_OPTION_3_FACE:
                    mask_index = 3
                if target == MASK_OPTION_4_CLOTHES:
                    mask_index = 4

                masks.append(segmented_masks.confidence_masks[mask_index])

            image_data = media_pipe_image.numpy_view()
            image_shape = image_data.shape

            # convert the image shape from "rgb" to "rgba" aka add the alpha channel
            if image_shape[-1] == 3:
                image_shape = (image_shape[0], image_shape[1], 4)

            mask_background_array = np.zeros(image_shape, dtype=np.uint8)
            mask_background_array[:] = (0, 0, 0, 255)

            mask_foreground_array = np.zeros(image_shape, dtype=np.uint8)
            mask_foreground_array[:] = (255, 255, 255, 255)

            mask_arrays = []
            for mask in masks:
                condition = np.stack((mask.numpy_view(),) * image_shape[-1], axis=-1) > 0.25
                mask_array = np.where(condition, mask_foreground_array, mask_background_array)
                mask_arrays.append(mask_array)

            # Merge our masks taking the maximum from each
            merged_mask_arrays = reduce(np.maximum, mask_arrays)

            return Image.fromarray(merged_mask_arrays)

    # How the script's is displayed in the UI. See https://gradio.app/docs/#components
    # for the different UI components you can use and how to create them.
    # Most UI components can return a value, such as a boolean for a checkbox.
    # The returned values are passed to the run method as parameters.
    def ui(self, is_img2img):
        if not is_img2img:
            return ()
        with gr.Accordion(title, open=False, elem_id="a_person_mask_generator_accordion") as accordion:
            with gr.Blocks():
                with gr.Row():
                    with gr.Column():
                        enabled = gr.Checkbox(
                            label="Enable",
                            value=False,
                            elem_id="a_person_mask_generator_enable_checkbox",
                        )

                        gr.HTML("<div style='margin: 8px 0px !important;'>* You probably want to be on the 'Inpaint' or 'Inpaint Upload' tab to make use of the mask settings.</div>")

                        mask_targets = gr.Dropdown(
                            label="Mask",
                            multiselect=True,
                            choices=[
                                MASK_OPTION_0_BACKGROUND,
                                MASK_OPTION_1_HAIR,
                                MASK_OPTION_2_BODY,
                                MASK_OPTION_3_FACE,
                                MASK_OPTION_4_CLOTHES,
                            ],
                            value=[MASK_OPTION_3_FACE],
                            elem_id="a_person_mask_generator_mask_dropdown",
                            interactive=True,
                        )

                        gr.HTML("<div style='margin: 8px 0px !important;'>** Preview is not available on 'Inpaint' tab.</div>")

                        preview_button = gr.Button(value="Preview Mask", elem_id="person_mask_generator_preview_button", )

                    with gr.Column():
                        preview_mask_image = gr.Image(value=None, label="Mask Preview", show_label=True, interactive=False, height=256, width=256,
                                                      elem_id="a_person_mask_generator_preview_mask_image")

            def update_preview_image(mask_targets: list[str]):
                try:
                    mask_image = self.generate_mask(image=self.img2img, mask_targets=mask_targets)

                    return {
                        preview_mask_image: gr.update(value=mask_image)
                    }
                except:
                    pass

            # change handlers
            mask_targets.change(
                fn=update_preview_image,
                inputs=mask_targets,
                outputs=preview_mask_image
            )

            enabled.change(
                fn=update_preview_image,
                inputs=mask_targets,
                outputs=preview_mask_image
            )

            preview_button.click(
                fn=update_preview_image,
                inputs=mask_targets,
                outputs=preview_mask_image
            )

            return [
                enabled,
                mask_targets,
            ]

    # From: https://github.com/LonicaMewinsky/gif2gif/blob/main/scripts/gif2gif.py
    # Grab the img2img image components for update later
    # Maybe there's a better way to do this?
    def after_component(self, component, **kwargs):
        def update_image(image: Image):
            self.img2img = image


        if component.elem_id == "img2img_image":
            self.img2img_image = component
            self.img2img_image.change(fn=update_image, inputs=[self.img2img_image])
            return self.img2img_image
        if component.elem_id == "img2img_sketch":
            self.img2img_sketch = component
            self.img2img_sketch.change(fn=update_image, inputs=[self.img2img_sketch])
            return self.img2img_sketch
        # The inpaint component is borked.  No Preview for that tab yet.
        #if component.elem_id == "img2maskimg":
        #    self.img2maskimg = component
        #    self.img2maskimg.select(fn=update_image, inputs=[self.img2maskimg])
        #    return self.img2maskimg
        if component.elem_id == "inpaint_sketch":
            self.inpaint_sketch = component
            self.inpaint_sketch.change(fn=update_image, inputs=[self.inpaint_sketch])
            return self.inpaint_sketch
        if component.elem_id == "img_inpaint_base":
            self.img_inpaint_base = component
            self.img_inpaint_base.change(fn=update_image, inputs=[self.img_inpaint_base])
            return self.img_inpaint_base

        return component


        #def img2img_change(image):
        #    try:
        #        self.img2img = image
        #    except:
        #        pass
#
        #if component.elem_id == "":
        #    image_component_ids = [
        #        "img2img_image",
        #        "img2img_sketch",
        #        "img2maskimg",
        #        "inpaint_sketch",
        #        "img_inpaint_base"
        #    ]
        #
        # component.change(fn=img2img_change, inputs=component)

    """
    This function is called very early during processing begins for AlwaysVisible scripts.
    You can modify the processing object (p) here, inject hooks, etc.
    args contains all values returned by components from ui()
    """

    def before_process(self, p, enabled: bool, mask_targets: list[str]):
        if enabled and len(p.init_images) > 0 and mask_targets:
            p.image_mask = self.generate_mask(image=p.init_images[-1], mask_targets=mask_targets)
