load(
    "@pyoxidizer//:default_python_distribution.bzl",
    "default_python_distribution",
)


def make_exe():
    dist = default_python_distribution()
    policy = dist.make_python_packaging_policy()
    python_config = dist.make_python_config(
        run_module="zomboid_saver_ui",
        packaging_policy=policy,
    )
    return dist.to_python_executable(
        name="zomboid_saver",
        packaging_policy=policy,
        config=python_config,
    )


def default_build_targets():
    return {"zomboid-saver": make_exe()}
