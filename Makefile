APP_NAME := Vigilia
BUILD_DIR := build

build:
	bash build.sh

ipa: build

test:
	mkdir -p $(BUILD_DIR)
	xcrun swiftc -parse-as-library src/Core/*.swift tests/*.swift -o $(BUILD_DIR)/logic-tests
	./$(BUILD_DIR)/logic-tests

sounds:
	python3 scripts/generate_sounds.py --out $(BUILD_DIR)/sounds

clean:
	rm -rf $(BUILD_DIR)

.PHONY: build ipa test sounds clean
