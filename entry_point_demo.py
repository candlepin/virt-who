from virtwho.config import load_source_classes, ConfigSection


if __name__ == "__main__":
    sources = load_source_classes()
    for name in sources.keys():
        print("type: \"%s\" :: loaded class: %s" % (name, ConfigSection.class_for_type(name)))