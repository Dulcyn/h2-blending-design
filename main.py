from opt import H2DesignOpt
import json


def main():
    with open('data/parameters.json', 'r') as f:
        data = json.load(f)

    opt = H2DesignOpt(data)
    opt.build()
    


    return


if __name__ == "__main__":
    main()