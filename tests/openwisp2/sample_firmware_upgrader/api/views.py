from openwisp_firmware_upgrader.api.views import BuildListView as BaseBuildListView


class BuildListView(BaseBuildListView):
    pass


build_list = BuildListView.as_view()
